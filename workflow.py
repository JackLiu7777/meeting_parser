import json
import re

from document_selection import build_final_document_counts, sanitize_risk_facts
from llm_client import stream_chat
from prompts import build_document_list_text, prompt_compliance_plan, prompt_extract_meeting_facts


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def parse_risk_fact_response(text: str) -> list[dict]:
    """Parse model JSON output and keep only usable risk facts."""
    raw = (text or "").strip()
    if not raw:
        return []

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    candidates = [raw]
    object_match = re.search(r"\{.*\}", raw, flags=re.S)
    if object_match:
        candidates.append(object_match.group(0))
    array_match = re.search(r"\[.*\]", raw, flags=re.S)
    if array_match:
        candidates.append(array_match.group(0))

    for candidate in candidates:
        try:
            return sanitize_risk_facts(json.loads(candidate))
        except Exception:
            continue
    return []


async def run_workflow(transcript: str, pre_meeting: dict = None, company_name: str = None):
    """串行生成两份文书，yield SSE 字符串。"""
    # Step 1：合规计划书
    yield sse("progress", {"stage": "doc1", "message": "正在生成合规计划书..."})
    doc1_parts = []
    async for chunk in stream_chat(prompt_compliance_plan(transcript, pre_meeting, company_name)):
        doc1_parts.append(chunk)
        yield sse("doc1_chunk", {"text": chunk})
    compliance_plan = "".join(doc1_parts)
    yield sse("doc1_done", {})

    # Step 2：先抽取会议事实、风险类型和原文证据
    yield sse("progress", {"stage": "facts", "message": "正在识别会议风险点和文书依据..."})
    fact_parts = []
    try:
        async for chunk in stream_chat(prompt_extract_meeting_facts(transcript, pre_meeting)):
            fact_parts.append(chunk)
        risk_facts = parse_risk_fact_response("".join(fact_parts))
    except Exception:
        risk_facts = []
    yield sse("facts_done", {"count": len(risk_facts)})

    # Step 3：文书清单
    yield sse("progress", {"stage": "doc2", "message": "正在生成文书清单..."})
    document_counts = build_final_document_counts(
        pre_meeting,
        transcript,
        risk_facts=risk_facts,
    )
    document_list = build_document_list_text(document_counts)
    yield sse("doc2_chunk", {"text": document_list})
    yield sse("doc2_done", {})

    yield sse("done", {
        "doc1": compliance_plan,
        "doc2": document_list,
        "risk_facts": risk_facts,
    })
