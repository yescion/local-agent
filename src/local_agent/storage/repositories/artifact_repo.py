"""Artifact repository."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from local_agent.artifacts.models import Artifact, ArtifactSummary
from local_agent.storage.models import ArtifactRow, parse_utc, utcnow


class ArtifactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _to_model(self, row: ArtifactRow) -> Artifact:
        return Artifact(
            id=row.id,
            agent_id=row.agent_id,
            thread_id=row.thread_id,
            name=row.name,
            path=row.path,
            tool_name=row.tool_name,
            description=row.description,
            size_bytes=row.size_bytes,
            created_at=parse_utc(row.created_at),
        )

    def create(
        self,
        agent_id: str,
        thread_id: str,
        name: str,
        path: str,
        *,
        tool_name: str | None = None,
        description: str | None = None,
        size_bytes: int | None = None,
    ) -> Artifact:
        row = ArtifactRow(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            thread_id=thread_id,
            name=name,
            path=path,
            tool_name=tool_name,
            description=description,
            size_bytes=size_bytes,
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.commit()
        return self._to_model(row)

    def get(self, artifact_id: str) -> Artifact | None:
        row = self.session.get(ArtifactRow, artifact_id)
        return self._to_model(row) if row else None

    def list_by_thread(self, thread_id: str) -> list[Artifact]:
        rows = self.session.scalars(
            select(ArtifactRow)
            .where(ArtifactRow.thread_id == thread_id)
            .order_by(ArtifactRow.created_at.desc())
        ).all()
        return [self._to_model(r) for r in rows]

    def list_by_agent(self, agent_id: str) -> list[Artifact]:
        rows = self.session.scalars(
            select(ArtifactRow)
            .where(ArtifactRow.agent_id == agent_id)
            .order_by(ArtifactRow.created_at.desc())
        ).all()
        return [self._to_model(r) for r in rows]

    def count_by_thread(self, thread_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count()).select_from(ArtifactRow).where(
                    ArtifactRow.thread_id == thread_id
                )
            )
            or 0
        )

    def count_by_agent(self, agent_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count()).select_from(ArtifactRow).where(
                    ArtifactRow.agent_id == agent_id
                )
            )
            or 0
        )

    def summary_by_thread(self, thread_id: str, *, max_names: int = 3) -> ArtifactSummary:
        artifacts = self.list_by_thread(thread_id)
        if not artifacts:
            return ArtifactSummary.empty()
        return ArtifactSummary(
            count=len(artifacts),
            names=[a.name for a in artifacts[:max_names]],
        )

    def summary_by_agent(self, agent_id: str, *, max_names: int = 3) -> ArtifactSummary:
        artifacts = self.list_by_agent(agent_id)
        if not artifacts:
            return ArtifactSummary.empty()
        return ArtifactSummary(
            count=len(artifacts),
            names=[a.name for a in artifacts[:max_names]],
        )

    def find_by_path(self, thread_id: str, path: str) -> Artifact | None:
        row = self.session.scalar(
            select(ArtifactRow).where(
                ArtifactRow.thread_id == thread_id,
                ArtifactRow.path == path,
            )
        )
        return self._to_model(row) if row else None

    def delete_by_agent(self, agent_id: str) -> int:
        result = self.session.execute(
            delete(ArtifactRow).where(ArtifactRow.agent_id == agent_id)
        )
        self.session.commit()
        return result.rowcount or 0

    def delete_by_thread(self, thread_id: str) -> list[str]:
        rows = self.session.scalars(
            select(ArtifactRow).where(ArtifactRow.thread_id == thread_id)
        ).all()
        paths = [r.path for r in rows]
        self.session.execute(delete(ArtifactRow).where(ArtifactRow.thread_id == thread_id))
        self.session.commit()
        return paths
