"""Agent manager - create, destroy, chat."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from pathlib import Path

from rich.console import Console
from sqlalchemy.orm import Session, sessionmaker

import shutil

from local_agent.agent.models import AgentInstance, ConversationPreview, Persona
from local_agent.agent.system_directives import default_system_directives
from local_agent.agent.thread_config import ThreadConfig
from local_agent.artifacts.manager import ArtifactManager
from local_agent.artifacts.models import Artifact, ArtifactSummary
from local_agent.agent.exceptions import ChatTurnCancelled
from local_agent.agent.runtime import AgentRuntime
from local_agent.config.models import Settings
from local_agent.llm.litellm_client import LiteLLMClient
from local_agent.memory.canvas import CanvasManager
from local_agent.memory.compactor import MemoryCompactor
from local_agent.memory.long_term import LongTermMemory
from local_agent.memory.retriever import MemoryRetriever
from local_agent.memory.short_term import ShortTermMemory
from local_agent.skills.registry import SkillRegistry
from local_agent.skills.watcher import SkillAutoReloader
from local_agent.agent.resolvers import resolve_ref
from local_agent.storage.repositories.agent_repo import AgentRepository
from local_agent.storage.repositories.artifact_repo import ArtifactRepository
from local_agent.storage.repositories.memory_repo import MemoryRepository
from local_agent.storage.repositories.message_repo import MessageRepository, ThreadRepository
from local_agent.tools.router import ToolRouter

logger = logging.getLogger(__name__)


class AgentManager:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.data_dir = Path(settings.app.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "refs").mkdir(exist_ok=True)
        (self.data_dir / "canvas").mkdir(exist_ok=True)
        (self.data_dir / "personas").mkdir(exist_ok=True)
        self.artifacts_dir = self.data_dir / settings.app.artifacts.subdir
        self.artifacts_dir.mkdir(exist_ok=True)
        self._runtimes: dict[str, AgentRuntime] = {}
        self._active_chats: dict[str, tuple[asyncio.Task[Any], AgentRuntime]] = {}
        self._skill_reload_listeners: list[Callable[[int], None]] = []
        self._skill_auto_reloader: SkillAutoReloader | None = None
        if settings.skills.auto_reload:
            self._start_skill_auto_reload()

    def add_skill_reload_listener(self, callback: Callable[[int], None]) -> None:
        """Register a callback invoked after an automatic skill hot-reload."""
        self._skill_reload_listeners.append(callback)

    def _start_skill_auto_reload(self) -> None:
        if self._skill_auto_reloader is not None:
            return

        def _on_skill_files_changed() -> None:
            count = self.reload_skills()
            logger.info("Skill hot-reload: %d skill(s) rescanned", count)
            for listener in self._skill_reload_listeners:
                try:
                    listener(count)
                except Exception:
                    logger.exception("Skill reload listener failed")

        self._skill_auto_reloader = SkillAutoReloader(
            self.settings.skills.directories,
            on_reload=_on_skill_files_changed,
        )
        self._skill_auto_reloader.start()
        logger.debug("Skill auto-reload watcher started")

    def stop_skill_auto_reload(self) -> None:
        if self._skill_auto_reloader is None:
            return
        self._skill_auto_reloader.stop()
        self._skill_auto_reloader = None

    def _session(self) -> Session:
        return self.session_factory()

    def _build_skill_registry(self, session: Session) -> SkillRegistry:
        tool_router = ToolRouter()
        registry = SkillRegistry(
            directories=self.settings.skills.directories,
            tool_router=tool_router,
            session=session,
            exclude_dir_names=self.settings.skills.exclude_dir_names,
        )
        registry.scan_directories()
        return registry

    def create_agent(
        self,
        name: str,
        persona: Persona | None = None,
        skills: list[str] | None = None,
        llm_override: dict | None = None,
        memory_scope: str = "agent",
    ) -> AgentInstance:
        session = self._session()
        try:
            agent_repo = AgentRepository(session)
            skill_registry = self._build_skill_registry(session)
            active_content = ""
            active_id = None
            skill_ids = skills or []
            if skill_ids:
                for sid in skill_ids:
                    meta = skill_registry.get_skill(sid)
                    if meta:
                        active_content = meta.content
                        active_id = meta.id
                        break
            agent = agent_repo.create(
                name=name,
                persona=persona or Persona(),
                skills=skill_ids,
                llm_override=llm_override,
                memory_scope=memory_scope,
                active_skill_id=active_id,
                active_skill_content=active_content or None,
            )
            thread_repo = ThreadRepository(session)
            thread_repo.create(agent.id, title=f"{name} 默认会话")
            return agent
        finally:
            session.close()

    def get_agent(self, agent_id: str) -> AgentInstance | None:
        session = self._session()
        try:
            return AgentRepository(session).get(agent_id)
        finally:
            session.close()

    def list_agents(self) -> list[AgentInstance]:
        session = self._session()
        try:
            return AgentRepository(session).list_all()
        finally:
            session.close()

    def list_agents_with_preview(self) -> list[tuple[AgentInstance, ConversationPreview]]:
        session = self._session()
        try:
            agents = AgentRepository(session).list_all()
            thread_repo = ThreadRepository(session)
            message_repo = MessageRepository(session)
            result: list[tuple[AgentInstance, ConversationPreview]] = []
            for agent in agents:
                threads = thread_repo.list_by_agent(agent.id)
                if threads:
                    preview = message_repo.get_thread_preview(threads[0].id)
                else:
                    preview = ConversationPreview.empty()
                result.append((agent, preview))
            return result
        finally:
            session.close()

    def delete_agent(self, agent_id: str) -> bool:
        session = self._session()
        try:
            return AgentRepository(session).delete(agent_id)
        finally:
            session.close()

    def list_threads(self, agent_id: str):
        session = self._session()
        try:
            return ThreadRepository(session).list_by_agent(agent_id)
        finally:
            session.close()

    def list_threads_with_preview(
        self, agent_id: str
    ) -> list[tuple]:
        session = self._session()
        try:
            thread_repo = ThreadRepository(session)
            message_repo = MessageRepository(session)
            artifact_repo = ArtifactRepository(session)
            result = []
            for thread in thread_repo.list_by_agent(agent_id):
                preview = message_repo.get_thread_preview(thread.id)
                summary = artifact_repo.summary_by_thread(thread.id)
                result.append((thread, preview, summary.count, summary.names))
            return result
        finally:
            session.close()

    def list_all_threads_with_preview(self) -> list[tuple]:
        """List all threads across every agent, sorted by last activity."""
        session = self._session()
        try:
            agent_repo = AgentRepository(session)
            agents = {a.id: a for a in agent_repo.list_all()}
            thread_repo = ThreadRepository(session)
            message_repo = MessageRepository(session)
            artifact_repo = ArtifactRepository(session)
            result = []
            for agent_id, agent in agents.items():
                for thread in thread_repo.list_by_agent(agent_id):
                    preview = message_repo.get_thread_preview(thread.id)
                    summary = artifact_repo.summary_by_thread(thread.id)
                    result.append(
                        (thread, preview, summary.count, summary.names, agent.name)
                    )

            def _sort_key(item: tuple) -> str:
                thread, preview, *_rest = item
                if preview.last_active:
                    return preview.last_active.isoformat()
                return thread.updated_at

            result.sort(key=_sort_key, reverse=True)
            return result
        finally:
            session.close()

    def create_thread(self, agent_id: str, title: str | None = None):
        session = self._session()
        try:
            return ThreadRepository(session).create(agent_id, title=title)
        finally:
            session.close()

    def get_thread(self, thread_id: str):
        session = self._session()
        try:
            return ThreadRepository(session).get(thread_id)
        finally:
            session.close()

    def get_thread_config(self, thread_id: str) -> ThreadConfig:
        session = self._session()
        try:
            return ThreadRepository(session).get_config(thread_id)
        finally:
            session.close()

    def get_thread_config_detail(self, thread_id: str) -> dict:
        """Return session overrides with inherited Agent defaults and system prompts."""
        session = self._session()
        try:
            thread = ThreadRepository(session).get(thread_id)
            if not thread:
                raise ValueError(f"Thread not found: {thread_id}")
            agent = AgentRepository(session).get(thread.agent_id)
            if not agent:
                raise ValueError(f"Agent not found: {thread.agent_id}")

            override = ThreadRepository(session).get_config(thread_id)
            effective = self._apply_thread_config(agent, override)
            registry = self._build_skill_registry(session)

            if override.skills is not None:
                effective_skill_ids = list(override.skills)
                effective_skills: list[str] | None = list(override.skills)
            elif agent.skills:
                effective_skill_ids = list(agent.skills)
                effective_skills = None
            else:
                effective_skill_ids = [s.id for s in registry.list_skills()]
                effective_skills = None

            directives = default_system_directives()
            preview = "\n\n".join(
                [effective.persona.to_system_prompt(), *directives]
            )

            return {
                "title": override.title,
                "persona": override.persona.model_dump() if override.persona else None,
                "skills": override.skills,
                "llm_override": override.llm_override,
                "agent_id": agent.id,
                "agent_name": agent.name,
                "agent_defaults": agent.persona.model_dump(),
                "agent_skills": list(agent.skills),
                "effective_persona": effective.persona.model_dump(),
                "effective_skills": effective_skills,
                "effective_skill_ids": effective_skill_ids,
                "has_persona_override": override.persona is not None,
                "has_skills_override": override.skills is not None,
                "system_directives": directives,
                "system_prompt_preview": preview,
            }
        finally:
            session.close()

    def update_thread_config(self, thread_id: str, config: ThreadConfig) -> ThreadConfig:
        session = self._session()
        try:
            updated = ThreadRepository(session).update_config(thread_id, config)
            thread = ThreadRepository(session).get(thread_id)
            if thread:
                agent = AgentRepository(session).get(thread.agent_id)
                if agent:
                    effective = self._apply_thread_config(agent, config)
                    MessageRepository(session).patch_base_system_persona(
                        thread_id,
                        effective.persona.to_system_prompt(),
                    )
            self._evict_runtime_for_thread(thread_id)
            return updated
        finally:
            session.close()

    def delete_thread(self, thread_id: str) -> bool:
        session = self._session()
        try:
            thread = ThreadRepository(session).get(thread_id)
            if not thread:
                return False
            artifact_paths = ArtifactRepository(session).delete_by_thread(thread_id)
            for path_str in artifact_paths:
                path = Path(path_str)
                if path.is_file():
                    path.unlink(missing_ok=True)
            artifact_dir = self.artifacts_dir / thread.agent_id / thread_id
            if artifact_dir.is_dir():
                shutil.rmtree(artifact_dir, ignore_errors=True)
            ThreadRepository(session).delete(thread_id)
            self._evict_runtime_for_thread(thread_id)
            return True
        finally:
            session.close()

    def _evict_runtime_for_thread(self, thread_id: str) -> None:
        keys = [k for k in self._runtimes if k.endswith(f":{thread_id}")]
        for key in keys:
            self._runtimes.pop(key, None)

    def get_thread_preview(self, thread_id: str) -> ConversationPreview:
        session = self._session()
        try:
            return MessageRepository(session).get_thread_preview(thread_id)
        finally:
            session.close()

    def list_artifacts(
        self, agent_id: str, thread_id: str | None = None
    ) -> list[Artifact]:
        session = self._session()
        try:
            artifact_manager = ArtifactManager(session, self.artifacts_dir)
            if thread_id:
                effective_agent = agent_id
                if not effective_agent:
                    thread = ThreadRepository(session).get(thread_id)
                    if thread:
                        effective_agent = thread.agent_id
                if effective_agent:
                    artifact_manager.sync_thread_artifacts(effective_agent, thread_id)
                return artifact_manager.list_by_thread(thread_id)
            if agent_id:
                agent_path = self.artifacts_dir / agent_id
                if agent_path.is_dir():
                    for thread_dir in agent_path.iterdir():
                        if thread_dir.is_dir():
                            artifact_manager.sync_thread_artifacts(agent_id, thread_dir.name)
            return artifact_manager.list_by_agent(agent_id)
        finally:
            session.close()

    def get_artifact_summary(
        self, *, agent_id: str | None = None, thread_id: str | None = None
    ) -> ArtifactSummary:
        session = self._session()
        try:
            repo = ArtifactRepository(session)
            if thread_id:
                return repo.summary_by_thread(thread_id)
            if agent_id:
                return repo.summary_by_agent(agent_id)
            return ArtifactSummary.empty()
        finally:
            session.close()

    def resolve_agent(self, ref: str) -> AgentInstance | None:
        return resolve_ref(self.list_agents(), ref, lambda a: a.id)

    def resolve_default_agent(self) -> AgentInstance | None:
        """Return the agent with the most recently active non-empty thread."""
        session = self._session()
        try:
            agents = AgentRepository(session).list_all()
            if not agents:
                return None
            thread_repo = ThreadRepository(session)
            message_repo = MessageRepository(session)
            best_agent: AgentInstance | None = None
            best_active: str | None = None
            for agent in agents:
                for thread in thread_repo.list_by_agent(agent.id):
                    preview = message_repo.get_thread_preview(thread.id)
                    if preview.turn_count == 0:
                        continue
                    active_at = (
                        preview.last_active.isoformat()
                        if preview.last_active
                        else thread.updated_at
                    )
                    if best_active is None or active_at > best_active:
                        best_active = active_at
                        best_agent = agent
            if best_agent:
                return best_agent
            for agent in agents:
                threads = thread_repo.list_by_agent(agent.id)
                if not threads:
                    continue
                if best_active is None or threads[0].updated_at > best_active:
                    best_active = threads[0].updated_at
                    best_agent = agent
            return best_agent or agents[0]
        finally:
            session.close()

    def resolve_thread(self, agent_id: str, ref: str):
        return resolve_ref(self.list_threads(agent_id), ref, lambda t: t.id)

    def get_or_create_runtime(
        self,
        agent_id: str,
        thread_id: str | None = None,
        console: Console | None = None,
    ) -> AgentRuntime:
        cache_key = f"{agent_id}:{thread_id or 'default'}"
        if cache_key in self._runtimes:
            return self._runtimes[cache_key]

        session = self._session()
        agent_repo = AgentRepository(session)
        agent = agent_repo.get(agent_id)
        if not agent:
            session.close()
            raise ValueError(f"Agent not found: {agent_id}")

        thread_repo = ThreadRepository(session)
        if thread_id:
            thread = thread_repo.get(thread_id)
            if not thread:
                session.close()
                raise ValueError(f"Thread not found: {thread_id}")
        else:
            threads = thread_repo.list_by_agent(agent_id)
            thread_id = threads[0].id if threads else thread_repo.create(agent_id).id

        thread_config = thread_repo.get_config(thread_id)
        effective_agent = self._apply_thread_config(agent, thread_config)

        skill_registry = self._build_skill_registry(session)
        tool_router = skill_registry.tool_router
        llm_override = effective_agent.llm_override or agent.llm_override
        llm = LiteLLMClient(self.settings.llm, llm_override)
        short_term = ShortTermMemory(
            self.settings.memory.short_term,
            self.data_dir / "refs",
        )
        compactor = MemoryCompactor(self.settings.memory, llm)
        memory_repo = MemoryRepository(session)
        message_repo = MessageRepository(session)
        long_term = LongTermMemory(
            self.settings.memory.long_term, llm, memory_repo, self.data_dir
        ) if self.settings.memory.enabled else None
        retriever = MemoryRetriever(
            self.settings.memory.retrieval, memory_repo, message_repo
        ) if self.settings.memory.enabled else None
        canvas = CanvasManager(
            session, self.data_dir / "canvas", self.settings.memory.short_term.canvas_max_tokens
        ) if self.settings.memory.short_term.canvas_enabled else None
        artifact_manager = (
            ArtifactManager(session, self.artifacts_dir)
            if self.settings.app.artifacts.enabled
            else None
        )

        runtime = AgentRuntime(
            agent=effective_agent,
            settings=self.settings,
            llm=llm,
            tool_router=tool_router,
            skill_registry=skill_registry,
            message_repo=message_repo,
            thread_repo=thread_repo,
            agent_repo=agent_repo,
            short_term=short_term,
            compactor=compactor,
            long_term=long_term,
            retriever=retriever,
            canvas=canvas,
            artifact_manager=artifact_manager,
            thread_id=thread_id,
            console=console,
            thread_config=thread_config,
        )
        self._runtimes[cache_key] = runtime
        return runtime

    @staticmethod
    def _apply_thread_config(agent: AgentInstance, config: ThreadConfig) -> AgentInstance:
        data = agent.model_dump()
        if config.persona is not None:
            data["persona"] = config.persona.model_dump()
        if config.skills is not None:
            data["skills"] = config.skills
        if config.llm_override is not None:
            data["llm_override"] = config.llm_override
        return AgentInstance.model_validate(data)

    def reload_skills(
        self,
        agent_id: str | None = None,
        thread_id: str | None = None,
    ) -> int:
        """Reload skills for cached runtimes (or a specific agent/thread)."""
        if not self._runtimes:
            session = self._session()
            try:
                registry = self._build_skill_registry(session)
                return registry.rescan()
            finally:
                session.close()

        if agent_id:
            prefix = f"{agent_id}:{thread_id or 'default'}"
            matched = [
                rt
                for key, rt in self._runtimes.items()
                if key == prefix or (not thread_id and key.startswith(f"{agent_id}:"))
            ]
            if thread_id:
                matched = [rt for key, rt in self._runtimes.items() if key == prefix]
            if not matched:
                return 0
            return matched[-1].reload_skills()

        last_count = 0
        for runtime in self._runtimes.values():
            last_count = runtime.reload_skills()
        return last_count

    def reload_skill(self, skill_id: str) -> bool:
        """Reload a single skill across cached runtimes, or from disk if none."""
        if self._runtimes:
            reloaded = False
            for runtime in self._runtimes.values():
                if not runtime.skill_registry.get_skill(skill_id):
                    continue
                runtime.skill_registry.reload(skill_id)
                if runtime.agent.active_skill_id == skill_id:
                    meta = runtime.skill_registry.get_skill(skill_id)
                    if meta:
                        runtime.agent.active_skill_content = meta.content
                        runtime.agent_repo.update_active_skill(
                            runtime.agent.id, meta.id, meta.content
                        )
                runtime.refresh_skill_context_in_messages()
                reloaded = True
            return reloaded

        session = self._session()
        try:
            registry = self._build_skill_registry(session)
            registry.reload(skill_id)
            return True
        except KeyError:
            return False
        finally:
            session.close()

    def _register_active_chat(self, thread_id: str, runtime: AgentRuntime) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._active_chats[thread_id] = (task, runtime)

    def _unregister_active_chat(self, thread_id: str) -> None:
        self._active_chats.pop(thread_id, None)

    def cancel_chat(self, thread_id: str) -> bool:
        """Request cooperative cancellation of an in-flight chat turn."""
        entry = self._active_chats.get(thread_id)
        if entry:
            _task, runtime = entry
            runtime.request_cancel()
            _task.cancel()
            return True
        runtime = self._find_runtime_by_thread(thread_id)
        if runtime is not None:
            runtime.request_cancel()
            return True
        return False

    def _find_runtime_by_thread(self, thread_id: str) -> AgentRuntime | None:
        for runtime in self._runtimes.values():
            if runtime.thread_id == thread_id:
                return runtime
        return None

    async def chat(
        self,
        agent_id: str,
        message: str,
        thread_id: str | None = None,
        console: Console | None = None,
        stream: bool = True,
        on_stream_event=None,
        attachment_ids: list[str] | None = None,
        reference_ids: list[str] | None = None,
    ) -> str:
        runtime = self.get_or_create_runtime(agent_id, thread_id, console)
        active_thread_id = runtime.thread_id
        runtime.reset_cancel_state()
        self._register_active_chat(active_thread_id, runtime)
        try:
            result = await runtime.chat_turn(
                message,
                stream=stream,
                on_stream_event=on_stream_event,
                attachment_ids=attachment_ids or [],
                reference_ids=reference_ids or [],
            )
            # SSE 流式对话：标题生成与记忆提取在后台执行，避免回答结束后长时间阻塞连接。
            if stream and on_stream_event is not None:
                asyncio.create_task(runtime.drain_memory_tasks())
            else:
                await runtime.drain_memory_tasks()
            return result
        except (ChatTurnCancelled, asyncio.CancelledError):
            return ""
        finally:
            self._unregister_active_chat(active_thread_id)
            runtime.clear_stream_event_handler()
            runtime.reset_cancel_state()
