import httpx
import logging
from io import BytesIO
from urllib.parse import unquote, urlparse

from docx import Document

logger = logging.getLogger(__name__)


def _decode_text_content(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("gbk", errors="replace")


def _extract_docx_content(content: bytes) -> str:
    document = Document(BytesIO(content))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    table_lines = []
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                table_lines.append(" | ".join(cells))
    return "\n".join(paragraphs + table_lines)


def _guess_file_ext(filename_or_url: str, content_type: str = "") -> str:
    path = unquote(urlparse(filename_or_url).path).lower()
    if path.endswith(".docx"):
        return ".docx"
    if path.endswith(".txt"):
        return ".txt"
    if "wordprocessingml.document" in content_type:
        return ".docx"
    if content_type.startswith("text/"):
        return ".txt"
    return ""


def extract_meeting_content(content: bytes, filename_or_url: str = "", content_type: str = "") -> str:
    ext = _guess_file_ext(filename_or_url, content_type)
    if ext == ".docx":
        return _extract_docx_content(content)
    if ext in ("", ".txt"):
        return _decode_text_content(content)
    raise ValueError("仅支持 .txt 和 .docx 格式的腾讯会议纪要")


async def download_file(url: str, timeout: int = 30) -> str:
    """
    从URL下载文件内容

    Args:
        url: 文件URL
        timeout: 超时时间（秒）

    Returns:
        文件内容（文本）

    Raises:
        httpx.HTTPError: 下载失败
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()

            content = extract_meeting_content(
                response.content,
                url,
                response.headers.get("content-type", ""),
            )

            logger.info(f"文件下载成功: {url} ({len(content)} 字符)")
            return content

    except httpx.HTTPError as e:
        logger.error(f"文件下载失败: {url} - {e}")
        raise
    except Exception as e:
        logger.error(f"下载过程出错: {e}")
        raise
