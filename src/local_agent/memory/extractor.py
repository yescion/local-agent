"""L0 → L1 memory atom extraction."""

from __future__ import annotations

import json
import re

from local_agent.llm.litellm_client import LiteLLMClient


EXTRACT_PROMPT = """从以下对话片段中提取原子记忆，以 JSON 输出：
{
  "atoms": [
    {
      "type": "fact|preference|constraint|conclusion",
      "content": "...",
      "confidence": 0.9
    }
  ]
}
只输出 JSON，不要其他文字。"""


class MemoryExtractor:
    def __init__(self, llm: LiteLLMClient) -> None:
        self.llm = llm

    async def extract(self, messages: list[dict]) -> list[dict]:
        if len(messages) < 2:
            return []
        recent = messages[-6:]
        text_parts = []
        for m in recent:
            role = m.get("role", "")
            content = m.get("content", "")
            if content:
                text_parts.append(f"{role}: {content}")
        if not text_parts:
            return []
        prompt = EXTRACT_PROMPT + "\n\n" + "\n".join(text_parts)
        resp = await self.llm.chat([{"role": "user", "content": prompt}])
        return self._parse_atoms(resp.content)

    def _parse_atoms(self, text: str) -> list[dict]:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return []
            data = json.loads(match.group())
            return data.get("atoms", [])
        except (json.JSONDecodeError, AttributeError):
            return []
