"""Hybrid memory retrieval (BM25 + optional vector with RRF)."""

from __future__ import annotations

from local_agent.config.models import RetrievalConfig
from local_agent.storage.repositories.memory_repo import MemoryRepository
from local_agent.storage.repositories.message_repo import MessageRepository


class MemoryRetriever:
    def __init__(
        self,
        config: RetrievalConfig,
        memory_repo: MemoryRepository,
        message_repo: MessageRepository | None = None,
    ) -> None:
        self.config = config
        self.memory_repo = memory_repo
        self.message_repo = message_repo

    def search_memory(
        self,
        agent_id: str,
        query: str,
        layer: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[str]:
        cap = limit or self.config.top_k
        results: list[str] = []
        if layer in (None, "L1"):
            atoms = self.memory_repo.search_atoms(agent_id, query, limit=cap)
            results.extend(f"[L1/{a.type}] {a.content}" for a in atoms if a)
        if layer in (None, "L2"):
            scenarios = self.memory_repo.list_scenarios(agent_id)
            q = query.lower()
            for s in scenarios:
                if q in (s.summary or "").lower() or q in s.title.lower():
                    results.append(f"[L2] {s.title}: {s.summary}")
        return results[:cap]

    def search_conversation(self, thread_id: str, query: str) -> list[str]:
        if not self.message_repo:
            return []
        msgs = self.message_repo.search(query, thread_id=thread_id, limit=self.config.top_k)
        return [
            f"[{m.get('role')}] {(m.get('content') or '')[:200]}"
            for m in msgs
            if m.get("content")
        ]

    def rrf_merge(self, *ranked_lists: list[str]) -> list[str]:
        """Reciprocal Rank Fusion."""
        scores: dict[str, float] = {}
        k = self.config.rrf_k
        for ranked in ranked_lists:
            for rank, item in enumerate(ranked, 1):
                scores[item] = scores.get(item, 0) + 1 / (k + rank)
        return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
