"""Built-in tool implementations."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def resolve_text_line_range(
    total_lines: int,
    offset: int | None,
    limit: int | None,
) -> tuple[int, int] | str:
    """Resolve a 1-based inclusive line range, or return an error message."""
    if offset == 0:
        return "错误：offset 不能为 0，请使用正数（从文件开头）或负数（从文件末尾倒数）"
    if limit is not None and limit < 0:
        return "错误：limit 不能为负数"
    if total_lines == 0:
        return "(空文件，0 行)"

    if offset is None:
        start_line = 1
    elif offset > 0:
        start_line = offset
    else:
        start_line = max(1, total_lines + offset + 1)

    if start_line > total_lines:
        return f"(文件共 {total_lines} 行，请求起始行 {start_line} 超出范围)"

    if limit is None:
        end_line = total_lines
    else:
        end_line = min(total_lines, start_line + limit - 1)

    return start_line, end_line


def format_text_line_range(
    selected: list[str],
    start_line: int,
    end_line: int,
    total_lines: int,
) -> str:
    header = f"(第 {start_line}-{end_line} 行，共 {total_lines} 行)\n"
    body = "\n".join(f"{i:6d}|{line}" for i, line in enumerate(selected, start=start_line))
    return header + body


def _count_text_lines(p: Path) -> int:
    count = 0
    with p.open(encoding="utf-8", errors="replace") as f:
        for _ in f:
            count += 1
    return count


def _read_text_line_range(p: Path, start_line: int, end_line: int) -> list[str]:
    lines: list[str] = []
    with p.open(encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if i < start_line:
                continue
            if i > end_line:
                break
            lines.append(line.rstrip("\n\r"))
    return lines


def read_text_file(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    """Read a text file, optionally by line range for large files."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"错误：文件不存在 — {path}"
        if not p.is_file():
            return f"错误：不是文件 — {path}"

        if offset is None and limit is None:
            return p.read_text(encoding="utf-8", errors="replace")

        total_lines = _count_text_lines(p)
        resolved = resolve_text_line_range(total_lines, offset, limit)
        if isinstance(resolved, str):
            return resolved
        start_line, end_line = resolved
        selected = _read_text_line_range(p, start_line, end_line)
        return format_text_line_range(selected, start_line, end_line, total_lines)
    except Exception as e:
        return f"错误：读取文件失败 — {e}"


def get_current_datetime() -> str:
    return datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")


def write_file(path: str, content: str, allowed_paths: list[Path] | None = None) -> str:
    try:
        p = Path(path).expanduser().resolve()
        if allowed_paths:
            allowed = False
            for base in allowed_paths:
                base = base.resolve()
                try:
                    p.relative_to(base)
                    allowed = True
                    break
                except ValueError:
                    continue
            if not allowed:
                return f"错误：路径不在白名单内 — {path}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {p}（{len(content)} 字符）"
    except Exception as e:
        return f"错误：写入失败 — {e}"


def list_dir(path: str = ".") -> str:
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"错误：目录不存在 — {path}"
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for e in entries[:200]:
            prefix = "[DIR] " if e.is_dir() else "      "
            lines.append(f"{prefix}{e.name}")
        if len(entries) > 200:
            lines.append(f"... 还有 {len(entries) - 200} 项")
        return "\n".join(lines) if lines else "(空目录)"
    except Exception as e:
        return f"错误：列目录失败 — {e}"


def grep_search(pattern: str, path: str = ".", max_results: int = 50) -> str:
    try:
        p = Path(path).expanduser().resolve()
        results: list[str] = []
        regex = re.compile(pattern)
        files = [p] if p.is_file() else list(p.rglob("*"))
        for f in files:
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    results.append(f"{f}:{i}: {line.strip()}")
                    if len(results) >= max_results:
                        return "\n".join(results) + f"\n...[截断，最多 {max_results} 条]"
        return "\n".join(results) if results else f"未找到匹配 '{pattern}' 的内容"
    except Exception as e:
        return f"错误：搜索失败 — {e}"


def run_shell(command: str, enabled: bool = False) -> str:
    _ = enabled
    return (
        "错误：宿主机 shell 已禁用。所有命令必须在 Daytona 沙盒中执行。\n"
        "请使用 daytona_sandbox 技能的工具：\n"
        "  1. sandbox_create — 创建沙盒（若尚无活动沙盒）\n"
        "  2. sandbox_exec — 在沙盒中执行命令\n"
        "  3. sandbox_session_exec — 在持久会话中执行（需保持 cd/环境变量时）"
    )


def recall_ref(node_id: str, refs_dir: Path) -> str:
    ref_path = refs_dir / f"{node_id}.md"
    if not ref_path.exists():
        return f"错误：未找到 ref — {node_id}"
    try:
        return ref_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"错误：读取 ref 失败 — {e}"


def make_manage_skills_handler(skill_manager: object) -> callable:
    def manage_skills(action: str, name: str = "") -> str:
        if action == "catalog":
            get_catalog = getattr(skill_manager, "get_catalog", None)
            if get_catalog:
                return get_catalog()  # type: ignore[misc]
            return "错误：技能目录不可用"
        if action == "list":
            skills = skill_manager.list_skills()  # type: ignore[attr-defined]
            return json.dumps(
                [s.id if hasattr(s, "id") else str(s) for s in skills],
                ensure_ascii=False,
            )
        if action == "load":
            if not name:
                return "错误：load 操作需要 name 参数"
            content = skill_manager.load_skill(name)  # type: ignore[attr-defined]
            return content
        return f"错误：未知 action — {action}，支持 catalog / list / load"
    return manage_skills
