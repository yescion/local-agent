"""Artifact manager — directory layout, tracking, and registration."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from local_agent.artifacts.extract import extract_for_agent, format_extractions
from local_agent.artifacts.models import Artifact, ArtifactSummary
from local_agent.storage.repositories.artifact_repo import ArtifactRepository
from local_agent.tools.session_context import format_session_context_lines

_USER_UPLOAD_TOOL = "user_upload"
_AUTO_SCAN_TOOL = "auto_scan"
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_ALLOWED_UPLOAD_EXTS = frozenset({
    ".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".xml",
    ".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx", ".py",
    ".sql", ".log", ".ini", ".toml", ".sh", ".bat", ".ps1",
    ".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".pdf", ".docx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",
})
_WRITE_SUCCESS_RE = re.compile(r"^已写入 (.+?)（(\d+) 字符）$")
_DOWNLOAD_SUCCESS_RE = re.compile(r"^已下载到 (.+?)（(\d+) 字节）$")
_WRITE_TOOLS = frozenset({"write_file"})
_DOWNLOAD_TOOLS = frozenset({"sandbox_fs_download_local"})
ARTIFACT_PATH_INSTRUCTION = (
    "向用户说明已保存的产物时，必须写出每个文件的完整绝对路径，"
    "不要仅说「产物目录」或「已保存」而不给出路径。"
)


class ArtifactManager:
    """Manage per-conversation artifact directories and metadata."""

    def __init__(self, session: Session, artifacts_root: Path) -> None:
        self.session = session
        self.root_dir = artifacts_root.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._repo = ArtifactRepository(session)

    def thread_dir(self, agent_id: str, thread_id: str) -> Path:
        """Return (and create) the artifact directory for a conversation."""
        path = self.root_dir / agent_id / thread_id
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    def uploads_dir(self, agent_id: str, thread_id: str) -> Path:
        """Return (and create) the user-upload directory for a conversation."""
        path = self.thread_dir(agent_id, thread_id) / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    def get(self, artifact_id: str) -> Artifact | None:
        return self._repo.get(artifact_id)

    @staticmethod
    def sanitize_upload_filename(name: str) -> str:
        """Strip path components and unsafe characters from an upload filename."""
        base = Path(name).name.strip()
        safe = re.sub(r"[^\w.\- ()\u4e00-\u9fff]", "_", base).strip("._")
        if not safe or safe in {".", ".."}:
            return "upload"
        return safe

    def is_allowed_upload(self, filename: str, size_bytes: int) -> str | None:
        """Return an error message if the upload is not allowed, else None."""
        if size_bytes <= 0:
            return "文件为空"
        if size_bytes > _MAX_UPLOAD_BYTES:
            return f"文件超过大小限制（{_MAX_UPLOAD_BYTES // (1024 * 1024)}MB）"
        ext = Path(filename).suffix.lower()
        if ext not in _ALLOWED_UPLOAD_EXTS:
            return f"不支持的文件类型: {ext or '(无扩展名)'}"
        return None

    def save_user_upload(
        self,
        agent_id: str,
        thread_id: str,
        filename: str,
        data: bytes,
    ) -> Artifact:
        """Save uploaded bytes under uploads/ and register as a user attachment."""
        error = self.is_allowed_upload(filename, len(data))
        if error:
            raise ValueError(error)

        uploads = self.uploads_dir(agent_id, thread_id)
        safe_name = self.sanitize_upload_filename(filename)
        unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        dest = (uploads / unique_name).resolve()
        if not str(dest).startswith(str(uploads)):
            raise ValueError("非法文件路径")

        dest.write_bytes(data)
        artifact = self.register(
            agent_id,
            thread_id,
            dest,
            tool_name=_USER_UPLOAD_TOOL,
            description="用户上传",
        )
        if not artifact:
            raise ValueError("注册附件失败")
        return artifact

    def get_user_upload(self, thread_id: str, artifact_id: str) -> Artifact | None:
        """Return a user-upload artifact if it belongs to the thread."""
        artifact = self._repo.get(artifact_id)
        if not artifact or artifact.thread_id != thread_id:
            return None
        if artifact.tool_name != _USER_UPLOAD_TOOL:
            return None
        return artifact

    def get_thread_artifact(self, thread_id: str, artifact_id: str) -> Artifact | None:
        """Return any session artifact belonging to the thread."""
        artifact = self._repo.get(artifact_id)
        if not artifact or artifact.thread_id != thread_id:
            return None
        return artifact

    def format_references_for_agent(
        self, thread_id: str, reference_ids: list[str]
    ) -> str:
        """Append absolute paths for @-referenced session files (no content extraction)."""
        lines: list[str] = []
        for artifact_id in reference_ids:
            artifact = self.get_thread_artifact(thread_id, artifact_id)
            if not artifact:
                continue
            lines.append(f"- {artifact.name}: {artifact.path}")
        if not lines:
            return ""
        return (
            "---\n"
            "引用的会话文件（请使用 read_text_file / read_excel 等工具按路径读取）：\n"
            + "\n".join(lines)
        )

    def format_attachments_for_agent(
        self, thread_id: str, attachment_ids: list[str]
    ) -> str:
        """Resolve attachment IDs and extract text for the agent."""
        extractions = []
        for artifact_id in attachment_ids:
            artifact = self.get_user_upload(thread_id, artifact_id)
            if not artifact:
                continue
            extracted = extract_for_agent(Path(artifact.path))
            extracted["name"] = artifact.name
            extracted["path"] = str(artifact.path)
            extractions.append(extracted)
        return format_extractions(extractions)

    def resolve_write_path(self, agent_id: str, thread_id: str, path: str) -> Path:
        """Resolve a write path; relative paths go under the thread artifact dir."""
        p = Path(path).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (self.thread_dir(agent_id, thread_id) / p).resolve()

    def is_under_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root_dir)
            return True
        except ValueError:
            return False

    def register(
        self,
        agent_id: str,
        thread_id: str,
        file_path: Path,
        *,
        tool_name: str | None = None,
        description: str | None = None,
    ) -> Artifact | None:
        """Record an artifact if the file exists and is not already registered."""
        resolved = file_path.resolve()
        if not resolved.is_file():
            return None

        existing = self._repo.find_by_path(thread_id, str(resolved))
        if existing:
            return existing

        return self._repo.create(
            agent_id=agent_id,
            thread_id=thread_id,
            name=resolved.name,
            path=str(resolved),
            tool_name=tool_name,
            description=description,
            size_bytes=resolved.stat().st_size,
        )

    def track_tool(
        self,
        tool_name: str,
        arguments: dict,
        result: str,
        agent_id: str,
        thread_id: str,
    ) -> Artifact | None:
        """Register an artifact from a successful file-write or sandbox-download tool call."""
        if tool_name not in _WRITE_TOOLS and tool_name not in _DOWNLOAD_TOOLS:
            return None
        if not result or result.startswith("错误"):
            return None

        description: str | None = None
        if tool_name in _DOWNLOAD_TOOLS:
            match = _DOWNLOAD_SUCCESS_RE.match(result.strip())
            remote_path = arguments.get("remote_path") or arguments.get("sandbox_path")
            if isinstance(remote_path, str) and remote_path:
                description = f"沙盒路径: {remote_path}"
        else:
            match = _WRITE_SUCCESS_RE.match(result.strip())
            arg_path = arguments.get("path")
            if isinstance(arg_path, str) and arg_path:
                resolved_name = Path(match.group(1)).name if match else ""
                if arg_path != resolved_name:
                    description = f"请求路径: {arg_path}"

        if not match:
            return None

        file_path = Path(match.group(1)).resolve()
        if not file_path.is_file():
            return None
        if not self.is_under_root(file_path):
            return None

        return self.register(
            agent_id,
            thread_id,
            file_path,
            tool_name=tool_name,
            description=description,
        )

    def sync_thread_artifacts(self, agent_id: str, thread_id: str) -> list[Artifact]:
        """Register on-disk files under the thread artifact dir not yet in the DB."""
        thread_path = self.thread_dir(agent_id, thread_id)
        uploads = self.uploads_dir(agent_id, thread_id)
        discovered: list[Artifact] = []
        for path in sorted(thread_path.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                path.resolve().relative_to(uploads)
                continue
            except ValueError:
                pass
            resolved = str(path.resolve())
            if self._repo.find_by_path(thread_id, resolved):
                continue
            artifact = self.register(
                agent_id,
                thread_id,
                path,
                tool_name=_AUTO_SCAN_TOOL,
                description="自动发现（未经过 write_file 登记）",
            )
            if artifact:
                discovered.append(artifact)
        return discovered

    def list_by_thread(self, thread_id: str) -> list[Artifact]:
        return self._repo.list_by_thread(thread_id)

    def list_by_agent(self, agent_id: str) -> list[Artifact]:
        return self._repo.list_by_agent(agent_id)

    def count_by_thread(self, thread_id: str) -> int:
        return self._repo.count_by_thread(thread_id)

    def count_by_agent(self, agent_id: str) -> int:
        return self._repo.count_by_agent(agent_id)

    def summary_by_thread(self, thread_id: str) -> ArtifactSummary:
        return self._repo.summary_by_thread(thread_id)

    def summary_by_agent(self, agent_id: str) -> ArtifactSummary:
        return self._repo.summary_by_agent(agent_id)

    def format_context_hint(self, agent_id: str, thread_id: str) -> str:
        """System-prompt snippet telling the model where to save outputs."""
        artifact_dir = self.thread_dir(agent_id, thread_id)
        uploads = self.uploads_dir(agent_id, thread_id)
        return (
            f"{format_session_context_lines(agent_id, thread_id)}\n"
            f"用户上传的附件保存在 {uploads}，可使用 read_text_file 等工具读取。\n"
            f"产物目录：本会话生成的文件请保存到 {artifact_dir}。\n"
            "使用 write_file 时可用相对路径（如 report.csv、output.md），"
            "将自动写入该目录；也可使用上述绝对路径。\n"
            "沙盒内生成的二进制文件（如 .xlsx）须用 sandbox_fs_download_local 下载到该目录；"
            "沙盒内源路径须英文/ASCII 文件名，下载时 local_path 可用中文命名；"
            "从 execution:sandbox 技能导出时传 execution_skill_id。\n"
            f"{ARTIFACT_PATH_INSTRUCTION}\n"
            "用户消息中可能已包含附件摘要，也可用 read_text_file / read_excel 按路径读取完整内容。\n"
            "用户可通过 /artifacts 或 `local-agent artifact list` 查看已生成的产物列表。"
        )

    def format_saved_paths_footer(self, artifacts: list[Artifact]) -> str:
        """Format a user-visible footer listing artifact absolute paths."""
        if not artifacts:
            return ""
        lines = ["\n\n产物文件路径："]
        for artifact in artifacts:
            lines.append(f"- {artifact.name}: {artifact.path}")
        return "\n".join(lines)

    def new_artifacts_since(
        self, thread_id: str, paths_before: set[str]
    ) -> list[Artifact]:
        """Return artifacts registered in this thread after paths_before was taken."""
        return [
            artifact
            for artifact in self.list_by_thread(thread_id)
            if str(artifact.path) not in paths_before
        ]

    def append_missing_paths(
        self, content: str, thread_id: str, paths_before: set[str]
    ) -> str:
        """Append absolute paths for new artifacts not already mentioned in content."""
        new_artifacts = self.new_artifacts_since(thread_id, paths_before)
        missing = [
            artifact
            for artifact in new_artifacts
            if str(artifact.path) not in content
        ]
        return content + self.format_saved_paths_footer(missing)
