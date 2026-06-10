"""Tool router - register, dispatch, and execute tools."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Callable

from local_agent.llm.litellm_client import ToolCall
from local_agent.tools.schema import ToolHandler, make_tool_schema, to_api_tool_name


class ToolRouter:
    def __init__(self, timeout: float = 120.0) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._schemas: dict[str, dict] = {}
        self._api_to_internal: dict[str, str] = {}
        self.timeout = timeout

    def register(self, name: str, fn: Callable, schema: dict) -> None:
        api_name = to_api_tool_name(name)
        self._handlers[name] = fn
        self._bind_api_name(api_name, name)
        api_schema = {
            **schema,
            "function": {**schema["function"], "name": api_name},
        }
        self._schemas[name] = api_schema

    def register_skill_tool(
        self,
        internal_name: str,
        short_name: str,
        fn: Callable,
        schema: dict,
    ) -> None:
        """Register a skill tool under its short API name (e.g. web_search)."""
        self._handlers[internal_name] = fn
        self._bind_api_name(short_name, internal_name)
        self._bind_api_name(to_api_tool_name(internal_name), internal_name)
        api_schema = {
            **schema,
            "function": {**schema["function"], "name": short_name},
        }
        self._schemas[internal_name] = api_schema

    def _bind_api_name(self, api_name: str, internal_name: str) -> None:
        self._api_to_internal[api_name] = internal_name

    def unregister(self, name: str) -> None:
        schema = self._schemas.pop(name, None)
        self._handlers.pop(name, None)
        if schema:
            api_name = schema["function"]["name"]
            if self._api_to_internal.get(api_name) == name:
                self._api_to_internal.pop(api_name, None)
            legacy_api = to_api_tool_name(name)
            if self._api_to_internal.get(legacy_api) == name:
                self._api_to_internal.pop(legacy_api, None)

    def get_openai_tools(self, skill_filter: list[str] | None = None) -> list[dict]:
        tools: list[dict] = []
        for internal_name, schema in self._schemas.items():
            if internal_name.startswith("skill."):
                if not skill_filter:
                    continue
                if not any(internal_name.startswith(f"skill.{s}.") for s in skill_filter):
                    continue
            tools.append(schema)
        return tools

    def list_tool_names(self) -> list[str]:
        return sorted(self._handlers.keys())

    @staticmethod
    def skill_id_for_tool(internal_name: str) -> str | None:
        if internal_name.startswith("skill."):
            parts = internal_name.split(".", 2)
            if len(parts) >= 2:
                return parts[1]
        return None

    @staticmethod
    def is_skill_tool_allowed(internal_name: str, allowed_skill_ids: list[str]) -> bool:
        skill_id = ToolRouter.skill_id_for_tool(internal_name)
        if skill_id is None:
            return True
        return skill_id in allowed_skill_ids

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        allowed_skill_ids: list[str] | None = None,
    ) -> str:
        name = self._api_to_internal.get(tool_call.name, tool_call.name)
        if name not in self._handlers:
            return f"错误：未知工具 — {name}"
        if allowed_skill_ids is not None:
            skill_id = self.skill_id_for_tool(name)
            if skill_id is not None and skill_id not in allowed_skill_ids:
                from local_agent.agent.skill_allowlist import format_skill_blocked_error

                return format_skill_blocked_error(
                    skill_id, tool_name=tool_call.name
                )
        try:
            args = json.loads(tool_call.arguments) if tool_call.arguments else {}
        except json.JSONDecodeError as e:
            return f"错误：参数 JSON 解析失败 — {e}"
        handler = self._handlers[name]
        start = time.monotonic()
        try:
            if asyncio.iscoroutinefunction(handler):
                result = await asyncio.wait_for(handler(**args), timeout=self.timeout)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(handler, **args), timeout=self.timeout
                )
            return str(result)
        except asyncio.TimeoutError:
            return f"错误：工具 {name} 执行超时"
        except TypeError as e:
            return f"错误：工具 {name} 参数错误 — {e}"
        except Exception as e:
            return f"错误：工具 {name} 执行失败 — {e}"
        finally:
            _ = time.monotonic() - start

    def register_builtin(
        self,
        manage_skills_fn: Callable,
        recall_ref_fn: Callable,
        memory_search_fn: Callable | None = None,
        conversation_search_fn: Callable | None = None,
        shell_enabled: bool = False,
        write_paths: list | None = None,
    ) -> None:
        from local_agent.tools.builtin import (
            get_current_datetime,
            grep_search,
            list_dir,
            read_text_file,
            run_shell,
            write_file,
        )

        self.register(
            "read_text_file",
            read_text_file,
            make_tool_schema(
                "read_text_file",
                "读取本地文本文件的内容。大文件请用 offset/limit 分批按行读取。",
                {
                    "path": {"type": "string", "description": "文件路径"},
                    "offset": {
                        "type": "integer",
                        "description": "起始行号（1 起算）。正数从文件开头计数，负数从末尾倒数（-1 为最后一行）。"
                        "仅读取部分行时提供。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "读取行数。与 offset 配合分批读取大文件；"
                        "仅提供 limit 时从第 1 行开始读取。",
                    },
                },
                required=["path"],
            ),
        )
        self.register(
            "get_current_datetime",
            lambda: get_current_datetime(),
            make_tool_schema("get_current_datetime", "获取当前本地日期和时间。", {}),
        )
        self.register(
            "manage_skills",
            manage_skills_fn,
            make_tool_schema(
                "manage_skills",
                "浏览工具箱（catalog）或加载技能完整文档（load）。所有工具均可直接调用，无需 load；"
                "catalog 返回与当轮上下文相同的工具箱清单；list 仅返回技能 ID。",
                {
                    "action": {
                        "type": "string",
                        "enum": ["catalog", "list", "load"],
                    },
                    "name": {"type": "string", "description": "技能 ID，load 时必填"},
                },
                required=["action"],
            ),
        )
        self.register(
            "write_file",
            lambda path, content: write_file(path, content, write_paths),
            make_tool_schema(
                "write_file",
                "将内容写入本地文件（受路径白名单限制）。",
                {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "文件内容"},
                },
                required=["path", "content"],
            ),
        )
        self.register(
            "list_dir",
            list_dir,
            make_tool_schema(
                "list_dir",
                "列出目录中的文件和子目录。",
                {"path": {"type": "string", "description": "目录路径，默认当前目录"}},
            ),
        )
        self.register(
            "grep",
            grep_search,
            make_tool_schema(
                "grep",
                "在文件或目录中搜索匹配正则表达式的文本行。",
                {
                    "pattern": {"type": "string", "description": "正则表达式"},
                    "path": {"type": "string", "description": "文件或目录路径"},
                },
                required=["pattern"],
            ),
        )
        self.register(
            "shell",
            lambda command: run_shell(command, enabled=shell_enabled),
            make_tool_schema(
                "shell",
                "已禁用：所有命令必须在 Daytona 沙盒中执行，请使用 sandbox_exec。",
                {"command": {"type": "string", "description": "要执行的命令"}},
                required=["command"],
            ),
        )
        self.register(
            "recall_ref",
            recall_ref_fn,
            make_tool_schema(
                "recall_ref",
                "按 node_id 取回之前卸载到 refs 的大段工具结果原文。",
                {"node_id": {"type": "string", "description": "引用节点 ID"}},
                required=["node_id"],
            ),
        )
        if memory_search_fn:
            self.register(
                "memory_search",
                memory_search_fn,
                make_tool_schema(
                    "memory_search",
                    "在长期记忆中搜索与查询相关的事实和结论。",
                    {"query": {"type": "string", "description": "搜索查询"}},
                    required=["query"],
                ),
            )
        if conversation_search_fn:
            self.register(
                "conversation_search",
                conversation_search_fn,
                make_tool_schema(
                    "conversation_search",
                    "在当前 Agent 的历史对话中全文搜索。",
                    {"query": {"type": "string", "description": "搜索查询"}},
                    required=["query"],
                ),
            )
