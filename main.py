import re
import json
import uuid
import asyncio
import logging
import logging.handlers
import os
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from workflow import run_workflow
from docx_exporter import text_to_docx
from task_manager import task_manager, TaskStatus
from download_utils import download_file, extract_meeting_content
from oss_client import oss_client
from db_client import db_client
from document_selection import build_final_document_counts

# ── 日志配置 ──────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    handlers=[
        logging.handlers.RotatingFileHandler(
            "logs/app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── 应用配置 ──────────────────────────────────────
MAX_UPLOAD_BYTES = 1 * 1024 * 1024  # 1MB，逐字稿 TXT 不会超过此限制

# CORS 允许的来源域名，多个用逗号分隔；未配置时默认允许所有（仅限本地开发）
_cors_origins_env = os.getenv("CORS_ORIGINS", "*")
allow_origins = [origin.strip() for origin in _cors_origins_env.split(",")] if _cors_origins_env else ["*"]

app = FastAPI(title="腾讯会议报告解析")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 内存 session：{session_id: {"transcript": str, "docs": [str, str], "risk_facts": list}}
sessions: dict = {}

DOC_TITLES = {
    1: "合规计划书",
    2: "文书清单",
}


def parse_transcript(raw: str) -> str:
    """去时间戳，保留 '发言人: 内容'。"""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(.+?)[（(]\d{2}:\d{2}:\d{2}[）)]\s*[:：]\s*(.+)", line)
        if m:
            lines.append(f"{m.group(1).strip()}: {m.group(2).strip()}")
        else:
            lines.append(line)
    return "\n".join(lines)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"文件过大，最大支持 {MAX_UPLOAD_BYTES // 1024}KB")
    raw = extract_meeting_content(raw_bytes, file.filename or "", file.content_type or "")
    transcript = parse_transcript(raw)
    if not transcript:
        raise HTTPException(400, "无法解析转录稿，请检查文件格式")
    sid = str(uuid.uuid4())
    sessions[sid] = {"transcript": transcript, "docs": ["", ""], "risk_facts": []}
    logger.info("upload ok  session=%s lines=%d", sid, transcript.count("\n") + 1)
    return {"session_id": sid, "lines": transcript.count("\n") + 1}


class GenRequest(BaseModel):
    session_id: str


class ProcessRequest(BaseModel):
    company_name: str
    meeting_id: str
    order_id: str
    file_url: str
    PreMeetingPreparation: dict | None = None

    @field_validator("PreMeetingPreparation", mode="before")
    @classmethod
    def parse_pre_meeting_preparation(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("PreMeetingPreparation 必须是 JSON 对象或 JSON 字符串") from exc
            if parsed in (None, ""):
                return None
            if not isinstance(parsed, dict):
                raise ValueError("PreMeetingPreparation 必须解析为 JSON 对象")
            return parsed
        raise ValueError("PreMeetingPreparation 必须是 JSON 对象")


@app.post("/api/generate/stream")
async def generate_stream(req: GenRequest):
    if req.session_id not in sessions:
        raise HTTPException(404, "session 不存在")
    session = sessions[req.session_id]
    logger.info("generate start  session=%s", req.session_id)

    async def event_stream():
        async for sse_str in run_workflow(session["transcript"]):
            yield sse_str
            if sse_str.startswith("event: done\n"):
                data_line = next(
                    (l for l in sse_str.splitlines() if l.startswith("data:")), None
                )
                if data_line:
                    payload = json.loads(data_line[5:])
                    session["docs"] = [
                        payload.get("doc1", ""),
                        payload.get("doc2", ""),
                    ]
                    session["risk_facts"] = payload.get("risk_facts", [])
                    logger.info("generate done  session=%s", req.session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/result/{session_id}")
async def get_result(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "session 不存在")
    docs = sessions[session_id]["docs"]
    return {"doc1": docs[0], "doc2": docs[1]}


@app.get("/api/download/{session_id}/{doc_index}")
async def download_docx(session_id: str, doc_index: int, background_tasks: BackgroundTasks):
    if session_id not in sessions:
        raise HTTPException(404, "session 不存在")
    if doc_index not in (1, 2):
        raise HTTPException(400, "doc_index 必须为 1/2")
    text = sessions[session_id]["docs"][doc_index - 1]
    if not text:
        raise HTTPException(400, "文书尚未生成")
    document_counts = None
    if doc_index == 2:
        session = sessions[session_id]
        document_counts = build_final_document_counts(
            None,
            session.get("transcript", ""),
            risk_facts=session.get("risk_facts", []),
        )
    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.close()
    text_to_docx(text, tmp.name, doc_index=doc_index, document_counts=document_counts)
    # 文件发送完成后自动删除临时文件
    background_tasks.add_task(os.remove, tmp.name)
    logger.info("download  session=%s doc=%d", session_id, doc_index)
    return FileResponse(
        tmp.name,
        filename=f"{DOC_TITLES[doc_index]}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        background=background_tasks,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


def parse_sse_message(sse_str: str) -> tuple[str | None, dict]:
    event_name = None
    data = {}
    for line in sse_str.splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            try:
                data = json.loads(line[5:])
            except json.JSONDecodeError:
                data = {}
    return event_name, data


def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def update_task_status_from_workflow_event(task_id: str, event_name: str | None, data: dict):
    if event_name == "progress":
        stage = data.get("stage")
        if stage == "doc1":
            task_manager.set_status(task_id, TaskStatus.GENERATING_COMPLIANCE_PLAN)
        elif stage == "doc2":
            task_manager.set_status(task_id, TaskStatus.GENERATING_DOCUMENT_LIST)
    elif event_name == "doc1_done":
        task_manager.set_status(task_id, TaskStatus.COMPLIANCE_PLAN_DONE)
    elif event_name == "doc2_done":
        task_manager.set_status(task_id, TaskStatus.DOCUMENT_LIST_DONE)


async def process_meeting_task(task_id: str, company_name: str, meeting_id: str, order_id: str, file_url: str, pre_meeting: dict = None):
    """后台处理任务"""
    write_lock = None
    write_lock_acquired = False
    try:
        if not task_manager.is_latest_task(task_id, meeting_id, order_id):
            logger.info(
                "task superseded before status init task=%s meeting_id=%s order_id=%s",
                task_id,
                meeting_id,
                order_id,
            )
            task_manager.set_superseded(task_id)
            return

        db_client.prepare_task_documents(meeting_id, order_id, "pending")

        # 1. 下载会议纪要
        raw_content = await download_file(file_url)
        transcript = parse_transcript(raw_content)

        if not task_manager.is_latest_task(task_id, meeting_id, order_id):
            logger.info(
                "task superseded before generation task=%s meeting_id=%s order_id=%s",
                task_id,
                meeting_id,
                order_id,
            )
            task_manager.set_superseded(task_id)
            return

        db_client.update_task_documents_status(meeting_id, order_id, "generating")

        docs = ["", ""]
        risk_facts = []

        # 2. 生成2份文书
        docs = ["", ""]
        async for sse_str in run_workflow(transcript, pre_meeting, company_name):
            event_name, event_data = parse_sse_message(sse_str)
            update_task_status_from_workflow_event(task_id, event_name, event_data)
            if event_name == "done":
                docs = [event_data.get("doc1", ""), event_data.get("doc2", "")]
                risk_facts = event_data.get("risk_facts", [])

        # 3. 转换为Word并上传OSS
        write_lock = task_manager.get_write_lock(meeting_id, order_id)
        await write_lock.acquire()
        write_lock_acquired = True

        if not task_manager.is_latest_task(task_id, meeting_id, order_id):
            logger.info(
                "task superseded before saving task=%s meeting_id=%s order_id=%s",
                task_id,
                meeting_id,
                order_id,
            )
            task_manager.set_superseded(task_id)
            return

        doc_info = [
            ("合规计划书", docs[0], "合规计划书.docx"),
            ("文书清单", docs[1], "文书清单.docx"),
        ]
        document_counts = build_final_document_counts(
            pre_meeting,
            transcript,
            risk_facts=risk_facts,
        )

        urls = {}
        for doc_index, (doc_type, doc_text, doc_name) in enumerate(doc_info, start=1):
            tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
            tmp.close()
            oss_path = f"upload/app/orders/{order_id}/{meeting_id}/{doc_name}"

            try:
                logger.info(
                    "开始生成Word task=%s doc_type=%s doc_index=%s tmp=%s",
                    task_id,
                    doc_type,
                    doc_index,
                    tmp.name,
                )
                text_to_docx(
                    doc_text,
                    tmp.name,
                    doc_index=doc_index,
                    document_counts=document_counts if doc_index == 2 else None,
                )

                logger.info(
                    "开始上传OSS task=%s doc_type=%s oss_path=%s",
                    task_id,
                    doc_type,
                    oss_path,
                )
                uploaded_url = oss_client.upload_file(tmp.name, oss_path)
                logger.info(
                    "OSS上传成功 task=%s doc_type=%s url=%s",
                    task_id,
                    doc_type,
                    uploaded_url,
                )

                logger.info(
                    "开始保存文书记录 task=%s doc_type=%s meeting_id=%s order_id=%s file_name=%s",
                    task_id,
                    doc_type,
                    meeting_id,
                    order_id,
                    doc_name,
                )
                db_client.save_latest_document(meeting_id, order_id, doc_type, uploaded_url, doc_name)
                urls[f"doc{doc_index}_url"] = uploaded_url
                logger.info(
                    "文书记录保存成功 task=%s doc_type=%s meeting_id=%s order_id=%s",
                    task_id,
                    doc_type,
                    meeting_id,
                    order_id,
                )
            except Exception:
                logger.exception(
                    "文书处理失败 task=%s doc_type=%s doc_index=%s doc_name=%s oss_path=%s",
                    task_id,
                    doc_type,
                    doc_index,
                    doc_name,
                    oss_path,
                )
                raise
            finally:
                try:
                    if os.path.exists(tmp.name):
                        os.remove(tmp.name)
                        logger.info("临时文件已删除 task=%s tmp=%s", task_id, tmp.name)
                except Exception:
                    logger.exception("临时文件删除失败 task=%s tmp=%s", task_id, tmp.name)

        urls["document_counts"] = document_counts
        urls["risk_facts"] = risk_facts

        # 4. 完成
        task_manager.set_completed(task_id, urls)

    except Exception as e:
        logger.exception("任务处理失败 task=%s meeting_id=%s order_id=%s", task_id, meeting_id, order_id)
        if task_manager.is_latest_task(task_id, meeting_id, order_id):
            try:
                db_client.update_task_documents_status(meeting_id, order_id, "failed")
            except Exception:
                logger.exception(
                    "任务失败状态写入数据库失败 task=%s meeting_id=%s order_id=%s",
                    task_id,
                    meeting_id,
                    order_id,
                )
        task_manager.set_failed(task_id, str(e))
    finally:
        if write_lock_acquired and write_lock:
            write_lock.release()


@app.post("/api/process")
async def process(req: ProcessRequest, background_tasks: BackgroundTasks):
    """提交处理任务（异步）"""
    task_id = task_manager.create_task(req.meeting_id, req.order_id)
    background_tasks.add_task(
        process_meeting_task,
        task_id,
        req.company_name,
        req.meeting_id,
        req.order_id,
        req.file_url,
        req.PreMeetingPreparation
    )
    logger.info(f"任务已提交: {task_id} - 公司: {req.company_name}")
    return {"success": True, "task_id": task_id, "message": "任务已提交，正在处理..."}


@app.get("/api/task/{task_id}/stream")
async def stream_task_status(task_id: str):
    """实时推送任务状态。"""
    queue = task_manager.subscribe(task_id)
    if not queue:
        raise HTTPException(404, "任务不存在")

    async def event_stream():
        try:
            while True:
                try:
                    task = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield format_sse("ping", {"task_id": task_id})
                    continue

                yield format_sse("task", task)
                if task_manager.is_terminal_status(task.get("status")):
                    break
        finally:
            task_manager.unsubscribe(task_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# 静态文件最后挂载，避免拦截 API 路由
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8124)
