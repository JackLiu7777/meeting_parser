import re
import json
import uuid
import logging
import logging.handlers
import os
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from workflow import run_workflow
from docx_exporter import text_to_docx
from download_utils import extract_meeting_content
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

app = FastAPI(title="会议纪要解析工具")
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


# 静态文件最后挂载，避免拦截 API 路由
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8124)
