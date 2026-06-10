"""Long-term memory orchestration (L0-L3 pipeline)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from local_agent.config.models import LongTermMemoryConfig
from local_agent.llm.litellm_client import LiteLLMClient
from local_agent.memory.aggregator import MemoryAggregator
from local_agent.memory.extractor import MemoryExtractor
from local_agent.memory.persona import PersonaDistiller
from local_agent.storage.repositories.memory_repo import MemoryRepository


class LongTermMemory:
    def __init__(
        self,
        config: LongTermMemoryConfig,
        llm: LiteLLMClient,
        memory_repo: MemoryRepository,
        data_dir: Path,
    ) -> None:
        self.config = config
        self.memory_repo = memory_repo
        self.extractor = MemoryExtractor(llm)
        self.aggregator = MemoryAggregator(
            llm, memory_repo, data_dir / "scenarios"
        )
        self.persona = PersonaDistiller(llm, memory_repo, data_dir / "personas")
        self._turn_count = 0
        self._extract_lock = asyncio.Lock()

    async def on_turn_complete(
        self, agent_id: str, thread_id: str, messages: list[dict]
    ) -> None:
        if not self.config.extraction_enabled:
            return
        async with self._extract_lock:
            await self._on_turn_complete_locked(agent_id, thread_id, messages)

    async def _on_turn_complete_locked(
        self, agent_id: str, thread_id: str, messages: list[dict]
    ) -> None:
        self._turn_count += 1
        atoms = await self.extractor.extract(messages)
        for atom in atoms:
            self.memory_repo.add_atom(
                agent_id=agent_id,
                thread_id=thread_id,
                atom_type=atom.get("type", "fact"),
                content=atom.get("content", ""),
                confidence=atom.get("confidence", 0.8),
            )
        if self._turn_count % self.config.aggregation_interval == 0:
            await self.aggregator.aggregate(agent_id)
        if self._turn_count % self.config.persona_update_interval == 0:
            await self.persona.distill(agent_id)

    def get_persona_context(self, agent_id: str) -> str:
        return self.persona.load_persona(agent_id)
