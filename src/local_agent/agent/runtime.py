"""Agent runtime - ReAct main loop."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from local_agent.agent.background_loop import BackgroundLoopService
from local_agent.agent.exceptions import ChatTurnCancelled
from local_agent.agent.models import AgentInstance
from local_agent.agent.skill_allowlist import build_allowlist_notice, format_skill_blocked_error
from local_agent.agent.system_directives import default_system_directives
from local_agent.agent.system_prompt import (
    L3_PERSONA_PREFIX,
    is_turn_context_system_message,
    patch_l3_persona_in_system_content,
    patch_persona_in_system_content,
)
from local_agent.memory.context_injection import (
    format_memory_context_block,
    is_memory_context_system_message,
    should_auto_inject_memory,
)
from local_agent.agent.thread_config import ThreadConfig
from local_agent.artifacts.manager import ARTIFACT_PATH_INSTRUCTION, ArtifactManager
from local_agent.config.models import Settings
from local_agent.llm.litellm_client import LiteLLMClient, ToolCall
from local_agent.llm.streaming import stream_with_thinking
from local_agent.memory.canvas import CanvasManager
from local_agent.memory.compactor import MemoryCompactor
from local_agent.memory.long_term import LongTermMemory
from local_agent.memory.retriever import MemoryRetriever
from local_agent.memory.short_term import ShortTermMemory
from local_agent.skills.registry import SkillRegistry
from local_agent.agent.thread_title import generate_thread_title, is_generic_title
from local_agent.storage.repositories.agent_repo import AgentRepository
from local_agent.storage.repositories.message_repo import MessageRepository, ThreadRepository
from local_agent.integrations.daytona_sandbox import (
    begin_turn,
    cleanup_turn,
    configure as configure_daytona,
    set_turn_artifact_context,
)
from local_agent.integrations.skill_runtime import (
    begin_execution_turn,
    cleanup_execution_sandboxes,
)
from local_agent.tools.builtin import make_manage_skills_handler, write_file
from local_agent.tools.router import ToolRouter
from local_agent.tools.schema import make_tool_schema
from local_agent.tools.session_context import (
    clear_turn_session_context,
    format_session_context_block,
    format_session_context_lines,
    get_session_context_json,
    set_turn_session_context,
)
from local_agent.tools.system_context import build_environment_context


class MaxToolRoundsExceeded(Exception):
    pass


class AgentRuntime:
    def __init__(
        self,
        agent: AgentInstance,
        settings: Settings,
        llm: LiteLLMClient,
        tool_router: ToolRouter,
        skill_registry: SkillRegistry,
        message_repo: MessageRepository,
        thread_repo: ThreadRepository,
        agent_repo: AgentRepository,
        short_term: ShortTermMemory,
        compactor: MemoryCompactor,
        long_term: LongTermMemory | None,
        retriever: MemoryRetriever | None,
        canvas: CanvasManager | None,
        artifact_manager: ArtifactManager | None,
        thread_id: str,
        console: Console | None = None,
        thread_config: ThreadConfig | None = None,
    ) -> None:
        self.agent = agent
        self.settings = settings
        self.llm = llm
        self.tool_router = tool_router
        self.skill_registry = skill_registry
        self.message_repo = message_repo
        self.thread_repo = thread_repo
        self.agent_repo = agent_repo
        self.short_term = short_term
        self.compactor = compactor
        self.long_term = long_term
        self.retriever = retriever
        self.canvas = canvas
        self.artifact_manager = artifact_manager
        self.thread_id = thread_id
        self.thread_config = thread_config or ThreadConfig()
        self.console = console or Console()
        self._stream_event_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._cancel_event = asyncio.Event()
        self.messages: list[dict] = []
        self._pending_skill_injection: str | None = None
        self._memory_tasks: set[asyncio.Task[None]] = set()
        self.background_loop = BackgroundLoopService(
            sleep_slice_secs=settings.background_loop.sleep_slice_secs
        )
        self._setup_tools()
        self._configure_integrations()
        self._init_messages()

    def _setup_tools(self) -> None:
        manage_fn = make_manage_skills_handler(self._SkillManagerAdapter(self))
        recall_fn = lambda node_id: self.short_term.recall(node_id)
        memory_search_fn = None
        conversation_search_fn = None
        if self.retriever:
            memory_search_fn = lambda query: json.dumps(
                self.retriever.search_memory(self.agent.id, query), ensure_ascii=False
            )
            conversation_search_fn = lambda query: json.dumps(
                self.retriever.search_conversation(self.thread_id, query), ensure_ascii=False
            )
        write_paths = [Path(p).resolve() for p in self.settings.tools.write_paths]
        if self.artifact_manager:
            root = self.artifact_manager.root_dir.resolve()
            if not any(root == p or root.is_relative_to(p) for p in write_paths):
                write_paths.append(root)
        self.tool_router.register_builtin(
            manage_skills_fn=manage_fn,
            recall_ref_fn=recall_fn,
            memory_search_fn=memory_search_fn,
            conversation_search_fn=conversation_search_fn,
            shell_enabled=self.settings.tools.shell_enabled,
            write_paths=write_paths,
        )
        self.tool_router.register(
            "get_session_context",
            lambda: get_session_context_json(),
            make_tool_schema(
                "get_session_context",
                "获取当前对话会话的 agent_id 与 thread_id；"
                "创建宿主机定时任务（job_create）须绑定会话才能在任务列表中显示。",
                {},
            ),
        )
        self._register_artifact_write_file(write_paths)

    def _register_artifact_write_file(self, write_paths: list) -> None:
        artifact_dir = None
        artifact_hint = ""
        if self.artifact_manager:
            artifact_dir = self.artifact_manager.thread_dir(
                self.agent.id, self.thread_id
            )
            artifact_hint = f" 产物文件建议保存到 {artifact_dir}，相对路径将自动写入该目录。"

        def write_handler(path: str, content: str) -> str:
            if self.artifact_manager:
                resolved = self.artifact_manager.resolve_write_path(
                    self.agent.id, self.thread_id, path
                )
                path = str(resolved)
            return write_file(path, content, write_paths)

        self.tool_router.register(
            "write_file",
            write_handler,
            make_tool_schema(
                "write_file",
                f"将内容写入本地文件（受路径白名单限制）。{artifact_hint}",
                {
                    "path": {
                        "type": "string",
                        "description": "文件路径；相对路径将写入当前会话产物目录",
                    },
                    "content": {"type": "string", "description": "文件内容"},
                },
                required=["path", "content"],
            ),
        )

    def _init_messages(self) -> None:
        stored = self.message_repo.load_messages(self.thread_id)
        if stored:
            self.messages = stored
            self._strip_turn_context_messages()
            self._ensure_artifact_context_in_messages()
            self._sync_persona_in_system_messages()
            self._sync_l3_persona_in_system_messages()
            self._ensure_system_directives_in_messages()
            self._migrate_skill_workflow_in_messages()
            return
        system_parts = [self.agent.persona.to_system_prompt()]
        if self.agent.active_skill_content:
            system_parts.append(f"Active Skill: {self.agent.active_skill_content}")
        system_parts.extend(default_system_directives())
        if self.long_term:
            persona_ctx = self.long_term.get_persona_context(self.agent.id)
            if persona_ctx:
                system_parts.append(f"L3 Persona:\n{persona_ctx}")
        if self.artifact_manager:
            system_parts.append(
                self.artifact_manager.format_context_hint(
                    self.agent.id, self.thread_id
                )
            )
        self.messages = [{"role": "system", "content": "\n\n".join(system_parts)}]

    def reload_skills(self) -> int:
        """Rescan skill files and refresh in-memory registry and context."""
        count = self.skill_registry.rescan()
        if self.agent.active_skill_id:
            meta = self.skill_registry.get_skill(self.agent.active_skill_id)
            if meta:
                self.agent.active_skill_content = meta.content
                self.agent_repo.update_active_skill(
                    self.agent.id, meta.id, meta.content
                )
            else:
                self.agent.active_skill_id = None
                self.agent.active_skill_content = ""
                self.agent_repo.update_active_skill(self.agent.id, None, "")
        self.refresh_skill_context_in_messages()
        return count

    def _sync_persona_in_system_messages(self) -> None:
        """Apply current persona (incl. per-thread overrides) to the base system prompt."""
        persona_prompt = self.agent.persona.to_system_prompt()
        for msg in self.messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content")
            if not isinstance(content, str) or is_turn_context_system_message(content):
                continue
            msg["content"] = patch_persona_in_system_content(content, persona_prompt)
            return

    def _sync_l3_persona_in_system_messages(self) -> None:
        """Refresh distilled L3 persona in the base system prompt when available."""
        if not self.long_term:
            return
        l3_persona = self.long_term.get_persona_context(self.agent.id)
        for msg in self.messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content")
            if not isinstance(content, str) or is_turn_context_system_message(content):
                continue
            if not l3_persona.strip() and L3_PERSONA_PREFIX not in content:
                return
            msg["content"] = patch_l3_persona_in_system_content(content, l3_persona)
            return

    def _strip_turn_context_messages(self) -> None:
        """Remove stale per-turn system blocks (environment, toolbox, etc.)."""
        self.messages = [
            msg
            for msg in self.messages
            if not (
                msg.get("role") == "system"
                and isinstance(msg.get("content"), str)
                and is_turn_context_system_message(msg["content"])
            )
        ]

    def _strip_memory_context_messages(self) -> None:
        self.messages = [
            msg
            for msg in self.messages
            if not (
                msg.get("role") == "system"
                and isinstance(msg.get("content"), str)
                and is_memory_context_system_message(msg["content"])
            )
        ]

    def _inject_relevant_memory(self, user_input: str) -> None:
        """Pre-fetch related L1/L2 memory for the current user turn."""
        if not self.retriever or not self.settings.memory.enabled:
            return
        retrieval = self.settings.memory.retrieval
        if not retrieval.auto_inject:
            return
        if not should_auto_inject_memory(user_input, retrieval):
            return

        self._strip_memory_context_messages()
        results = self.retriever.search_memory(
            self.agent.id,
            user_input.strip(),
            limit=retrieval.auto_inject_top_k,
        )
        block = format_memory_context_block(results)
        if block:
            self.messages.append({"role": "system", "content": block})

    def _ensure_system_directives_in_messages(self) -> None:
        """Backfill agent-wide directives missing from older persisted sessions."""
        for msg in self.messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                return
            missing = [
                directive
                for directive in default_system_directives()
                if directive.split("\n", 1)[0] not in content
            ]
            if missing:
                msg["content"] = content + "\n\n" + "\n\n".join(missing)
            return

    def _migrate_skill_workflow_in_messages(self) -> None:
        """Strip legacy per-skill blocks from old system prompts."""
        for msg in self.messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            cleaned = self._strip_legacy_skill_prompt_blocks(content)
            if cleaned != content:
                msg["content"] = cleaned
            return

    _LEGACY_PROMPT_PREFIXES = (
        "Available Skills:",
        "技能工具箱：",
        "工具执行环境：",
        "沙盒执行（强制）：",
        "环境上下文：每次用户消息前",
    )

    def _strip_legacy_skill_prompt_blocks(self, content: str) -> str:
        parts = content.split("\n\n")
        kept: list[str] = []
        for part in parts:
            if any(part.startswith(prefix) for prefix in self._LEGACY_PROMPT_PREFIXES):
                continue
            kept.append(part)
        marker = "交互与推理语言："
        if not any(marker in p for p in kept):
            kept.extend(default_system_directives())
        return "\n\n".join(kept)

    def _ensure_artifact_context_in_messages(self) -> None:
        if not self.artifact_manager:
            self._ensure_session_context_in_messages()
            return
        hint = self.artifact_manager.format_context_hint(
            self.agent.id, self.thread_id
        )
        for msg in self.messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if "产物目录：" in content:
                if "当前会话 agent_id:" not in content:
                    session_lines = format_session_context_lines(
                        self.agent.id, self.thread_id
                    )
                    content = session_lines + "\n\n" + content
                    msg["content"] = content
                if ARTIFACT_PATH_INSTRUCTION in content:
                    return
                msg["content"] = content + "\n" + ARTIFACT_PATH_INSTRUCTION
                return
        self.messages.insert(0, {"role": "system", "content": hint})

    def _ensure_session_context_in_messages(self) -> None:
        session_lines = format_session_context_lines(self.agent.id, self.thread_id)
        for msg in self.messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if is_turn_context_system_message(content):
                continue
            if "当前会话 agent_id:" in content:
                return
            msg["content"] = session_lines + "\n\n" + content
            return
        self.messages.insert(
            0, {"role": "system", "content": session_lines}
        )

    def refresh_skill_context_in_messages(self) -> None:
        for msg in self.messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if "Active Skill:" not in content:
                continue
            msg["content"] = self._patch_skill_sections(content)

    def _patch_skill_sections(self, content: str) -> str:
        parts = content.split("\n\n")
        patched: list[str] = []
        has_active = False
        for part in parts:
            if part.startswith("Active Skill:"):
                has_active = True
                if self.agent.active_skill_content:
                    patched.append(f"Active Skill: {self.agent.active_skill_content}")
                continue
            if any(part.startswith(p) for p in self._LEGACY_PROMPT_PREFIXES):
                continue
            patched.append(part)
        if self.agent.active_skill_content and not has_active:
            patched.insert(1, f"Active Skill: {self.agent.active_skill_content}")
        return "\n\n".join(patched)

    class _SkillManagerAdapter:
        def __init__(self, runtime: AgentRuntime) -> None:
            self.runtime = runtime

        def list_skills(self):
            allowed = set(self.runtime.get_effective_skill_ids())
            return [
                s
                for s in self.runtime.skill_registry.list_skills()
                if s.id in allowed
            ]

        def get_catalog(self) -> str:
            return self.runtime.skill_registry.get_skill_catalog(
                self.runtime.get_effective_skill_ids()
            )

        def load_skill(self, name: str) -> str:
            skill = self.runtime.skill_registry.get_skill(name.removesuffix(".md"))
            skill_id = skill.id if skill else name.removesuffix(".md")
            allowed = self.runtime.get_effective_skill_ids()
            if skill_id not in allowed:
                return format_skill_blocked_error(skill_id, action="加载")
            content = self.runtime.skill_registry.load_skill(name)
            if not content.startswith("错误"):
                self.runtime.agent.active_skill_content = content
                self.runtime.agent.active_skill_id = skill_id
                self.runtime.agent_repo.update_active_skill(
                    self.runtime.agent.id, skill_id, content
                )
                # Defer injection until after tool responses — inserting a system
                # message mid tool round breaks the tool_calls → tool message chain.
                self.runtime._pending_skill_injection = content
                tool_names = skill.tools if skill else []
                if tool_names:
                    tools_hint = "、".join(tool_names)
                    return (
                        f"已加载技能「{skill_id}」，以下工具现已可用：{tools_hint}\n\n"
                        f"{content}"
                    )
            return content

    def _configure_integrations(self) -> None:
        configure_daytona(self.settings.daytona)
        from local_agent.skills import workshop

        workshop.set_rescan_hook(self.reload_skills)

        def _unregister_skill(skill_id: str) -> None:
            self.skill_registry.unregister(skill_id)
            if self.agent.active_skill_id == skill_id:
                self.agent.active_skill_id = None
                self.agent.active_skill_content = ""
                self.agent_repo.update_active_skill(self.agent.id, None, "")
            self.refresh_skill_context_in_messages()

        workshop.set_unregister_hook(_unregister_skill)

    def _skill_allowlist_notice(self) -> str:
        if self.thread_config.skills is not None:
            return build_allowlist_notice(
                self.get_effective_skill_ids(),
                source="会话配置",
            )
        if self.agent.skills:
            return build_allowlist_notice(
                self.get_effective_skill_ids(),
                source="Agent 默认设置",
            )
        return ""

    def _inject_turn_context(self) -> None:
        """Inject per-turn environment + unified toolbox (refreshed each user message)."""
        self._strip_turn_context_messages()
        toolbox = self.skill_registry.get_toolbox_catalog(
            self.get_effective_skill_ids()
        )
        parts = [build_environment_context()]
        session_block = format_session_context_block()
        if session_block:
            parts.append(session_block)
        allowlist = self._skill_allowlist_notice()
        if allowlist:
            parts.append(allowlist)
        parts.append(toolbox)
        self.messages.append(
            {
                "role": "system",
                "content": "\n\n".join(parts),
            }
        )

    def get_effective_skill_ids(self) -> list[str]:
        if self.thread_config.skills is not None:
            return list(self.thread_config.skills)
        if self.agent.skills:
            return list(self.agent.skills)
        return [s.id for s in self.skill_registry.list_skills()]

    def get_tools(self) -> list[dict]:
        return self.tool_router.get_openai_tools(self.get_effective_skill_ids())

    def _emit_stream_event(self, event: str, data: dict[str, Any] | None = None) -> None:
        if self._stream_event_handler:
            self._stream_event_handler(event, data or {})

    async def chat_turn(
        self,
        user_input: str,
        stream: bool = True,
        on_stream_event: Callable[[str, dict[str, Any]], None] | None = None,
        attachment_ids: list[str] | None = None,
        reference_ids: list[str] | None = None,
    ) -> str:
        self._stream_event_handler = on_stream_event
        begin_turn()
        begin_execution_turn()
        set_turn_session_context(
            self.agent.id,
            self.thread_id,
            agent_name=self.agent.name,
        )
        if self.artifact_manager:
            artifact_dir = self.artifact_manager.thread_dir(
                self.agent.id, self.thread_id
            )
            set_turn_artifact_context(
                str(artifact_dir),
                str(self.artifact_manager.root_dir),
            )
        else:
            set_turn_artifact_context(None)
        try:
            return await self._chat_turn_body(
                user_input,
                stream=stream,
                attachment_ids=attachment_ids or [],
                reference_ids=reference_ids or [],
            )
        finally:
            clear_turn_session_context()
            self._cleanup_daytona_sandboxes()

    def clear_stream_event_handler(self) -> None:
        self._stream_event_handler = None

    def reset_cancel_state(self) -> None:
        self._cancel_event.clear()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def is_cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise ChatTurnCancelled()

    def _rollback_turn(self, turn_start_len: int) -> None:
        if len(self.messages) > turn_start_len:
            del self.messages[turn_start_len:]

    def _handle_turn_cancelled(self, turn_start_len: int) -> None:
        self._rollback_turn(turn_start_len)
        self._emit_stream_event("cancelled", {"reason": "user"})

    def _snapshot_artifact_paths(self) -> set[str]:
        if not self.artifact_manager:
            return set()
        return {
            str(artifact.path)
            for artifact in self.artifact_manager.list_by_thread(self.thread_id)
        }

    def _append_new_artifact_paths(
        self, content: str, paths_before: set[str]
    ) -> str:
        if not self.artifact_manager:
            return content
        updated = self.artifact_manager.append_missing_paths(
            content, self.thread_id, paths_before
        )
        if updated != content:
            self.console.print(updated[len(content) :], end="")
        return updated

    def _build_user_message_content(
        self,
        user_input: str,
        attachment_ids: list[str],
        reference_ids: list[str] | None = None,
    ) -> str:
        parts: list[str] = []
        if user_input.strip():
            parts.append(user_input.strip())
        if reference_ids and self.artifact_manager:
            ref_block = self.artifact_manager.format_references_for_agent(
                self.thread_id, reference_ids
            )
            if ref_block:
                parts.append(ref_block)
        if attachment_ids and self.artifact_manager:
            attachment_block = self.artifact_manager.format_attachments_for_agent(
                self.thread_id, attachment_ids
            )
            if attachment_block:
                parts.append(attachment_block)
        content = "\n\n".join(parts)
        if not content:
            content = "（用户仅发送了附件）"
        offloaded, _node = self.short_term.offload_if_large(content, "user_attachments")
        return offloaded

    async def _chat_turn_body(
        self,
        user_input: str,
        stream: bool = True,
        attachment_ids: list[str] | None = None,
        reference_ids: list[str] | None = None,
    ) -> str:
        turn_start_len = len(self.messages)
        try:
            return await self._chat_turn_body_inner(
                user_input,
                stream=stream,
                attachment_ids=attachment_ids,
                reference_ids=reference_ids,
            )
        except ChatTurnCancelled:
            self._handle_turn_cancelled(turn_start_len)
            raise
        except asyncio.CancelledError:
            self._handle_turn_cancelled(turn_start_len)
            raise

    async def _chat_turn_body_inner(
        self,
        user_input: str,
        stream: bool = True,
        attachment_ids: list[str] | None = None,
        reference_ids: list[str] | None = None,
    ) -> str:
        artifact_paths_before = self._snapshot_artifact_paths()
        self._inject_turn_context()
        user_content = self._build_user_message_content(
            user_input, attachment_ids or [], reference_ids or []
        )
        self.messages.append({"role": "user", "content": user_content})
        self._sync_l3_persona_in_system_messages()
        self._inject_relevant_memory(user_input)

        if self.compactor.should_compact(self.messages):
            self._raise_if_cancelled()
            self.console.print(
                f"\n[dim][SYSTEM] Auto-compacting context "
                f"({self.compactor.estimate_tokens(self.messages)} tokens)...[/dim]"
            )
            self.messages = await self.compactor.compact(
                self.messages, self.agent.active_skill_content
            )
            self._raise_if_cancelled()

        if self.canvas and self.settings.memory.short_term.canvas_enabled:
            canvas_msg = self.canvas.to_context_message(self.thread_id)
            if canvas_msg:
                self.messages.insert(1 if self.messages else 0, canvas_msg)

        tools = self.get_tools()
        final_content = ""

        for round_num in range(self.settings.agent.max_tool_rounds):
            self._raise_if_cancelled()
            thinking = ""
            if stream:
                final_content, thinking, tool_calls = await self._stream_round(tools)
            else:
                resp = await self.llm.chat(self.messages, tools=tools)
                final_content = resp.content
                tool_calls = resp.tool_calls or None
            self._raise_if_cancelled()

            if not tool_calls:
                final_content = self._append_new_artifact_paths(
                    final_content, artifact_paths_before
                )
                assistant_msg: dict = {"role": "assistant", "content": final_content}
                if thinking:
                    assistant_msg["thinking"] = thinking
                self.messages.append(assistant_msg)
                self._persist()
                self._schedule_memory_extraction()
                self._schedule_title_update(user_input, final_content)
                self._emit_stream_event("done", {"content": final_content})
                return final_content

            assistant_msg = {
                "role": "assistant",
                "content": final_content or None,
                "tool_calls": [tc.to_openai_dict() for tc in tool_calls],
                # DeepSeek requires reasoning_content on replay for tool-call turns.
                "thinking": thinking or "",
            }
            self.messages.append(assistant_msg)
            await self._handle_tools(tool_calls)
            self._raise_if_cancelled()
            tools = self.get_tools()
        else:
            return await self._finalize_after_max_tool_rounds(
                stream=stream, artifact_paths_before=artifact_paths_before
            )

    async def _finalize_after_max_tool_rounds(
        self, *, stream: bool, artifact_paths_before: set[str]
    ) -> str:
        """达到最大工具轮次后，通知模型并请求一次无工具的收尾答复。"""
        limit = self.settings.agent.max_tool_rounds
        limit_msg = (
            f"[系统提示] 已达到最大工具调用轮次（{limit}）。"
            "请根据目前已有的工具执行结果和上下文，直接向用户给出最终答复，"
            "不要再调用任何工具。"
        )
        self.console.print(f"\n[dim yellow][SYSTEM] {limit_msg}[/dim yellow]")
        self.messages.append({"role": "user", "content": limit_msg})

        thinking = ""
        if stream:
            final_content, thinking, _ = await self._stream_round(tools=None)
        else:
            resp = await self.llm.chat(self.messages, tools=None)
            final_content = resp.content

        final_content = self._append_new_artifact_paths(
            final_content, artifact_paths_before
        )
        assistant_msg: dict = {"role": "assistant", "content": final_content}
        if thinking:
            assistant_msg["thinking"] = thinking
        self.messages.append(assistant_msg)
        self._persist()
        self._schedule_memory_extraction()
        self._schedule_title_update(
            self._latest_user_message_for_title(), final_content
        )
        self._emit_stream_event("done", {"content": final_content})
        return final_content

    def _latest_user_message_for_title(self) -> str:
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str) and not content.startswith("[系统提示]"):
                    return content
        return ""

    def _schedule_title_update(
        self, user_message: str, assistant_message: str
    ) -> None:
        user_message = user_message.strip()
        assistant_message = assistant_message.strip()
        if not user_message:
            return

        thread = self.thread_repo.get(self.thread_id)
        if not thread or not is_generic_title(thread.title):
            return

        async def _run() -> None:
            try:
                title = await generate_thread_title(
                    self.llm, user_message, assistant_message
                )
                current = self.thread_repo.get(self.thread_id)
                if not current or not is_generic_title(current.title):
                    return
                self.thread_repo.update_title(self.thread_id, title)
                self._emit_stream_event("thread_title", {"title": title})
            except Exception as e:
                self.console.print(f"[dim red]会话标题生成失败: {e}[/dim red]")

        task = asyncio.create_task(_run())
        self._memory_tasks.add(task)
        task.add_done_callback(self._memory_tasks.discard)

    def _cleanup_daytona_sandboxes(self) -> None:
        try:
            exec_cleaned = cleanup_execution_sandboxes()
            if exec_cleaned:
                self.console.print(
                    f"[dim][SYSTEM] 已清理自创技能执行沙盒: {', '.join(exec_cleaned)}[/dim]"
                )
        except Exception as e:
            self.console.print(f"[dim red]自创技能沙盒清理失败: {e}[/dim red]")
        if not self.settings.daytona.auto_cleanup_on_turn_end:
            return
        try:
            cleaned = cleanup_turn()
            if cleaned:
                action = self.settings.daytona.cleanup_action
                self.console.print(
                    f"[dim][SYSTEM] 已自动{action}沙盒: {', '.join(cleaned)}[/dim]"
                )
        except Exception as e:
            self.console.print(f"[dim red]沙盒自动清理失败: {e}[/dim red]")

    async def _stream_round(
        self, tools: list[dict] | None
    ) -> tuple[str, str, list[ToolCall] | None]:
        thinking_started = False
        answer_started = False

        def on_thinking_start() -> None:
            nonlocal thinking_started
            if not thinking_started:
                self.console.print("\n[yellow][思考过程]:[/yellow]")
                thinking_started = True

        def on_answer_start() -> None:
            nonlocal answer_started
            if not answer_started:
                self.console.print("\n[green][最终答复]:[/green]")
                answer_started = True

        def on_thinking_chunk(text: str) -> None:
            self.console.print(text, end="")
            self._emit_stream_event("thinking", {"text": text})

        def on_content_chunk(text: str) -> None:
            self.console.print(text, end="")
            self._emit_stream_event("content", {"text": text})

        return await stream_with_thinking(
            self.llm,
            self.messages,
            tools=tools,
            on_thinking=on_thinking_chunk,
            on_content=on_content_chunk,
            on_thinking_start=on_thinking_start,
            on_answer_start=on_answer_start,
            cancel_check=self.is_cancel_requested,
        )

    async def _handle_tools(self, tool_calls: list[ToolCall]) -> None:
        self._pending_skill_injection = None
        allowed_skill_ids = self.get_effective_skill_ids()
        for tc in tool_calls:
            self._raise_if_cancelled()
            self._emit_stream_event(
                "tool_start", {"name": tc.name, "arguments": tc.arguments}
            )
            result = await self.tool_router.execute(
                tc, allowed_skill_ids=allowed_skill_ids
            )
            self._emit_stream_event(
                "tool_end", {"name": tc.name, "result": result[:2000]}
            )
            self._track_artifact(tc, result)
            result, node_id = self.short_term.offload_if_large(result, tc.name)
            if self.canvas and node_id:
                self.canvas.add_node(
                    self.thread_id,
                    f"tool:{tc.name}<br/>node_id: {node_id}",
                    node_id=node_id.replace("ref_", "n_"),
                )
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                }
            )
        self._flush_pending_skill_injection()

    def _track_artifact(self, tc: ToolCall, result: str) -> None:
        if not self.artifact_manager:
            return
        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
        except json.JSONDecodeError:
            return
        if not isinstance(args, dict):
            return
        self.artifact_manager.track_tool(
            tc.name,
            args,
            result,
            self.agent.id,
            self.thread_id,
        )

    def _flush_pending_skill_injection(self) -> None:
        if not self._pending_skill_injection:
            return
        self.messages.append(
            {
                "role": "system",
                "content": f"Active Skill: {self._pending_skill_injection}",
            }
        )
        self._pending_skill_injection = None

    def _persist(self) -> None:
        self.message_repo.save_messages(self.thread_id, self.messages)

    def _schedule_memory_extraction(self) -> None:
        if not self.long_term:
            return

        messages = list(self.messages)

        async def _run() -> None:
            try:
                await self.long_term.on_turn_complete(
                    self.agent.id, self.thread_id, messages
                )
            except Exception as e:
                self.console.print(f"[dim red]记忆提取失败: {e}[/dim red]")

        task = asyncio.create_task(_run())
        self._memory_tasks.add(task)
        task.add_done_callback(self._memory_tasks.discard)

    async def drain_memory_tasks(self) -> None:
        if self._memory_tasks:
            await asyncio.gather(*list(self._memory_tasks), return_exceptions=True)

    def load_history(self, thread_id: str) -> bool:
        msgs = self.message_repo.load_messages(thread_id)
        if not msgs:
            return False
        self.thread_id = thread_id
        self.messages = msgs
        return True

    def estimate_tokens(self) -> int:
        return self.compactor.estimate_tokens(self.messages)

    def run_background_iteration(self, prompt: str) -> None:
        loop_messages: list[dict] = []
        if self.agent.active_skill_content:
            loop_messages.append(
                {"role": "system", "content": f"Context: {self.agent.active_skill_content}"}
            )
        loop_messages.append({"role": "user", "content": prompt})

        async def _run() -> None:
            set_turn_session_context(
                self.agent.id,
                self.thread_id,
                agent_name=self.agent.name,
            )
            try:
                tools = self.get_tools()
                content, _, tool_calls = await stream_with_thinking(
                    self.llm, loop_messages, tools=tools
                )
                if tool_calls:
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "tool_calls": [tc.to_openai_dict() for tc in tool_calls],
                            "thinking": thinking or "",
                        }
                    )
                    allowed_skill_ids = self.get_effective_skill_ids()
                    for tc in tool_calls:
                        result = await self.tool_router.execute(
                            tc, allowed_skill_ids=allowed_skill_ids
                        )
                        self._track_artifact(tc, result)
                        loop_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "name": tc.name,
                                "content": result,
                            }
                        )
                    content, _, _ = await stream_with_thinking(
                        self.llm, loop_messages, tools=tools
                    )
                self.console.print(f"\n[blue][LOOP][/blue] {content}")
            finally:
                clear_turn_session_context()

        asyncio.run(_run())
