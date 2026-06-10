"""L2 → L3 persona distillation."""

from __future__ import annotations

from pathlib import Path

from local_agent.llm.litellm_client import LiteLLMClient
from local_agent.storage.repositories.memory_repo import MemoryRepository


class PersonaDistiller:
    def __init__(
        self,
        llm: LiteLLMClient,
        memory_repo: MemoryRepository,
        personas_dir: Path,
    ) -> None:
        self.llm = llm
        self.memory_repo = memory_repo
        self.personas_dir = personas_dir
        self.personas_dir.mkdir(parents=True, exist_ok=True)

    async def distill(self, agent_id: str) -> str:
        scenarios = self.memory_repo.list_scenarios(agent_id)
        atoms = self.memory_repo.list_atoms(agent_id, limit=50)
        context_parts = []
        for s in scenarios[:5]:
            context_parts.append(f"场景: {s.title} — {s.summary}")
        for a in atoms[:20]:
            context_parts.append(f"[{a.type}] {a.content}")
        if not context_parts:
            return ""
        prompt = (
            "根据以下记忆，蒸馏出用户/智能体的稳定画像（人设摘要，300字以内）：\n"
            + "\n".join(context_parts)
        )
        resp = await self.llm.chat([{"role": "user", "content": prompt}])
        persona_md = resp.content.strip()
        path = self.personas_dir / f"{agent_id}.md"
        path.write_text(f"# Persona: {agent_id}\n\n{persona_md}\n", encoding="utf-8")
        return persona_md

    def load_persona(self, agent_id: str) -> str:
        path = self.personas_dir / f"{agent_id}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""
