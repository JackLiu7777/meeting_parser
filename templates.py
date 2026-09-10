from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


BASE_DIR = Path(__file__).resolve().parent
REFERENCE_TEMPLATE_DIR = BASE_DIR / "reference_templates"

TEMPLATE_PATHS = {
    "compliance_plan": REFERENCE_TEMPLATE_DIR / "compliance_plan.docx",
    "document_list": REFERENCE_TEMPLATE_DIR / "document_list.docx",
}


def _clean_text(text: str) -> str:
    return " ".join((text or "").replace("\u3000", " ").split())


def _iter_blocks(doc: Document):
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _extract_table(table: Table) -> list[str]:
    rows = []
    for row in table.rows:
        cells = [_clean_text(cell.text) for cell in row.cells]
        if any(cells):
            rows.append(" | ".join(cells))
    return rows


def _load_docx_template(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"参考模板不存在: {path}")

    doc = Document(path)
    parts: list[str] = []
    table_index = 0

    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            text = _clean_text(block.text)
            if text:
                parts.append(text)
        elif isinstance(block, Table):
            table_index += 1
            rows = _extract_table(block)
            if rows:
                parts.append(f"【表格{table_index}】")
                parts.extend(rows)

    return "\n".join(parts)


TEMPLATE_COMPLIANCE_PLAN = _load_docx_template(TEMPLATE_PATHS["compliance_plan"])
TEMPLATE_DOCUMENT_LIST = _load_docx_template(TEMPLATE_PATHS["document_list"])

# 兼容旧函数名，避免其他模块未同步时直接报错。
TEMPLATE_CHECKLIST = TEMPLATE_COMPLIANCE_PLAN
TEMPLATE_DOCLIST = TEMPLATE_DOCUMENT_LIST
