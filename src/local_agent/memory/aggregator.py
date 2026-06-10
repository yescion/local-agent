"""L1 → L2 scenario aggregation."""

from __future__ import annotations

from pathlib import Path

from local_agent.llm.litellm_client import LiteLLMClient
from local_agent.storage.repositories.memory_repo import MemoryRepository


class MemoryAggregator:
    def __init__(
        self,
        llm: LiteLLMClient,
        memory_repo: MemoryRepository,
        scenarios_dir: Path,
    ) -> None:
        self.llm = llm
        self.memory_repo = memory_repo
        self.scenarios_dir = scenarios_dir
        self.scenarios_dir.mkdir(parents=True, exist_ok=True)

    async def aggregate(self, agent_id: str, title: str = "综合场景") -> str | None:
        atoms = self.memory_repo.list_atoms(agent_id, limit=20)
        if len(atoms) < 3:
            return None
        atom_text = "\n".join(f"- [{a.type}] {a.content}" for a in atoms)
        prompt = (
            f"将以下原子记忆聚合为一个场景摘要（200字以内）：\n{atom_text}"
        )
        resp = await self.llm.chat([{"role": "user", "content": prompt}])
        summary = resp.content.strip()
        atom_ids = [a.id for a in atoms]
        md_path = self.scenarios_dir / f"{agent_id}_{len(atom_ids)}.md"
        md_path.write_text(f"# {title}\n\n{summary}\n", encoding="utf-8")
        scenario = self.memory_repo.add_scenario(
            agent_id=agent_id,
            title=title,
            summary=summary,
            atom_ids=atom_ids,
            md_path=str(md_path),
        )
        return scenario.id
