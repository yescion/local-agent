"""Short-term memory: offload large tool results to refs."""

from __future__ import annotations

import uuid
from pathlib import Path

from local_agent.config.models import ShortTermMemoryConfig


class ShortTermMemory:
    def __init__(self, config: ShortTermMemoryConfig, refs_dir: Path) -> None:
        self.config = config
        self.refs_dir = refs_dir
        self.refs_dir.mkdir(parents=True, exist_ok=True)

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def offload_if_large(self, content: str, tool_name: str = "") -> tuple[str, str | None]:
        """Return (context_content, ref_path_or_node_id)."""
        if not self.config.offload_enabled:
            return self._truncate_legacy(content), None
        tokens = self.estimate_tokens(content)
        if tokens <= self.config.offload_threshold_tokens:
            return content, None
        node_id = f"ref_{uuid.uuid4().hex[:8]}"
        ref_path = self.refs_dir / f"{node_id}.md"
        header = f"# Tool Result: {tool_name}\n\n" if tool_name else ""
        ref_path.write_text(header + content, encoding="utf-8")
        preview = content[:4000] + ("..." if len(content) > 4000 else "")
        summary = (
            f"[OFFLOADED to {node_id}] 原文 {tokens} tokens 已卸载到 refs。\n"
            f"预览：{preview}\n"
            f"使用 recall_ref(node_id='{node_id}') 取回完整内容。"
        )
        return summary, node_id

    def recall(self, node_id: str) -> str:
        ref_path = self.refs_dir / f"{node_id}.md"
        if not ref_path.exists():
            return f"错误：未找到 ref — {node_id}"
        return ref_path.read_text(encoding="utf-8")

    def _truncate_legacy(self, content: str) -> str:
        if len(content) > 32000:
            return content[:8000] + "\n...[TRUNCATED]...\n" + content[-8000:]
        return content
