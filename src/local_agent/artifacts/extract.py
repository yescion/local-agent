"""Extract file content for agent context injection."""

from __future__ import annotations

from pathlib import Path

from local_agent.artifacts.file_preview import (
    build_spreadsheet_preview,
    build_table_preview,
    preview_kind,
)

USER_UPLOAD_TOOL = "user_upload"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_AGENT_EXTRACT_CHARS = 32_000

UPLOAD_ALLOWED_EXTENSIONS = frozenset({
    ".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".xml",
    ".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx", ".py",
    ".sql", ".log", ".ini", ".toml", ".sh", ".bat", ".ps1",
    ".csv", ".tsv", ".xlsx", ".xlsm", ".xls",
    ".pdf", ".docx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",
})


def _rows_to_markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    head = max_chars // 2
    tail = max_chars - head - 40
    return text[:head] + "\n\n…（中间内容已省略）…\n\n" + text[-tail:], True


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "（需要安装 pypdf 才能提取 PDF 文本，可使用 read_text_file 读取或请用户描述需求）"

    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts).strip() or "（PDF 未提取到文本，可能是扫描件）"
    except Exception as exc:
        return f"（PDF 解析失败: {exc}）"


def _extract_docx_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        return "（需要安装 python-docx 才能提取 Word 文本）"

    try:
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        return f"（Word 解析失败: {exc}）"


def extract_for_agent(path: Path, *, max_chars: int = MAX_AGENT_EXTRACT_CHARS) -> dict:
    """Return structured content for injecting into the user message."""
    if not path.is_file():
        return {
            "kind": "missing",
            "text": "（文件不存在）",
            "truncated": False,
        }

    kind = preview_kind(path)
    path_str = str(path.resolve())

    if kind == "image":
        return {
            "kind": "image",
            "text": (
                f"（图片文件）\n"
                f"绝对路径: {path_str}\n"
                "说明: 当前以文本模式注入；如需视觉分析请使用支持视觉的模型。"
            ),
            "truncated": False,
        }

    if kind == "spreadsheet":
        preview = build_spreadsheet_preview(path, size_bytes=path.stat().st_size)
        if preview and preview.get("sheets"):
            blocks: list[str] = []
            for sheet in preview["sheets"]:
                rows = sheet.get("rows") or []
                blocks.append(f"工作表: {sheet.get('name', '')}\n{_rows_to_markdown_table(rows)}")
            text = "\n\n".join(blocks)
            if preview.get("truncated"):
                text += "\n（表格内容已截断，完整文件见上述路径）"
            text, truncated = _truncate_text(text, max_chars)
            return {"kind": "spreadsheet", "text": text, "truncated": truncated}

    if kind == "table":
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        preview = build_table_preview(path, size_bytes=path.stat().st_size, delimiter=delimiter)
        if preview and preview.get("rows"):
            text = _rows_to_markdown_table(preview["rows"])
            if preview.get("truncated"):
                text += "\n（表格内容已截断，完整文件见上述路径）"
            text, truncated = _truncate_text(text, max_chars)
            return {"kind": "table", "text": text, "truncated": truncated}

    if kind == "pdf":
        text, truncated = _truncate_text(_extract_pdf_text(path), max_chars)
        return {"kind": "pdf", "text": text, "truncated": truncated}

    if path.suffix.lower() == ".docx":
        text, truncated = _truncate_text(_extract_docx_text(path), max_chars)
        return {"kind": "docx", "text": text, "truncated": truncated}

    if kind in ("text", "html"):
        raw = path.read_text(encoding="utf-8", errors="replace")
        text, truncated = _truncate_text(raw, max_chars)
        return {"kind": kind, "text": text, "truncated": truncated}

    return {
        "kind": "binary",
        "text": (
            f"（二进制或不支持自动解析的文件类型: {path.suffix or '无扩展名'}）\n"
            f"绝对路径: {path_str}\n"
            "可使用 read_text_file 尝试读取，或请用户说明如何处理。"
        ),
        "truncated": False,
    }


def format_extractions(items: list[dict]) -> str:
    """Format extracted attachment blocks for injection into the user message."""
    if not items:
        return ""
    blocks: list[str] = []
    for item in items:
        name = item.get("name", "附件")
        path = item.get("path", "")
        kind = item.get("kind", "")
        text = item.get("text", "")
        truncated = item.get("truncated", False)
        lines = [f"[附件: {name}]"]
        if path:
            lines.append(f"路径: {path}")
        if kind:
            lines.append(f"类型: {kind}")
        if truncated:
            lines.append("（内容已截断，完整文件见上述路径）")
        if text:
            lines.append(text)
        blocks.append("\n".join(lines))
    return "---\n" + "\n\n".join(blocks)


def format_extractions(extractions: list[dict]) -> str:
    """Format extracted attachment content for injection into the user message."""
    if not extractions:
        return ""
    blocks: list[str] = []
    for item in extractions:
        name = item.get("name", "附件")
        path = item.get("path", "")
        text = item.get("text", "")
        block = f"[附件: {name}]"
        if path:
            block += f"\n路径: {path}"
        if text:
            block += f"\n{text}"
        if item.get("truncated"):
            block += "\n（内容已截断，完整文件见上述路径）"
        blocks.append(block)
    return "\n\n---\n\n".join(blocks)
