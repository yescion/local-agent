"""Context compaction: simple (70/30) and full modes."""

from __future__ import annotations

from local_agent.agent.system_prompt import (
    ACTIVE_SKILL_PREFIX,
    dedupe_active_skill_in_messages,
)
from local_agent.config.models import MemoryConfig
from local_agent.llm.litellm_client import LiteLLMClient


class MemoryCompactor:
    def __init__(self, config: MemoryConfig, llm: LiteLLMClient) -> None:
        self.config = config
        self.llm = llm

    def estimate_tokens(self, messages: list[dict]) -> int:
        text = "".join(str(m.get("content", "")) for m in messages)
        return max(1, len(text) // 4)

    def should_compact(self, messages: list[dict]) -> bool:
        if not self.config.enabled:
            return False
        return self.estimate_tokens(messages) >= self.config.compact_threshold

    async def compact(
        self,
        messages: list[dict],
        active_skill_content: str = "",
    ) -> list[dict]:
        if len(messages) < 4:
            return messages
        if self.config.compact_mode == "simple":
            return await self._compact_simple(messages, active_skill_content)
        return await self._compact_simple(messages, active_skill_content)

    async def _compact_simple(
        self,
        messages: list[dict],
        active_skill_content: str,
    ) -> list[dict]:
        ratio = self.config.compact_split_ratio
        split_idx = int(len(messages) * ratio)
        to_summarize = messages[:split_idx]
        keep_fresh = messages[split_idx:]
        summary = await self.llm.summarize(
            to_summarize,
            "用一段话总结以上对话，保留关键事实和当前目标。",
        )
        if active_skill_content:
            keep_fresh = dedupe_active_skill_in_messages(keep_fresh)
        new_history: list[dict] = [
            {"role": "system", "content": f"PREVIOUS SUMMARY: {summary}"}
        ]
        if active_skill_content:
            new_history.insert(
                0,
                {
                    "role": "system",
                    "content": f"{ACTIVE_SKILL_PREFIX} {active_skill_content}",
                },
            )
        new_history.extend(keep_fresh)
        return new_history
