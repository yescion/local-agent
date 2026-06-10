"""LiteLLM client wrapper."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

# Skip remote model cost map fetch (GitHub); use bundled backup instead.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
import uuid

from local_agent.config.models import LLMConfig
from local_agent.llm.messages import prepare_messages_for_api

logger = logging.getLogger(__name__)

_litellm_debug_enabled = False
_litellm_file_handler: logging.FileHandler | None = None


def _redirect_litellm_loggers_to_file(log_file: Path) -> logging.FileHandler:
    from litellm._logging import (
        _secret_filter,
        verbose_logger,
        verbose_proxy_logger,
        verbose_router_logger,
    )

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - "
            "%(filename)s:%(lineno)s - %(message)s"
        )
    )
    file_handler.addFilter(_secret_filter)

    for litellm_logger in (verbose_logger, verbose_router_logger, verbose_proxy_logger):
        for handler in list(litellm_logger.handlers):
            if isinstance(handler, logging.StreamHandler):
                stream = getattr(handler, "stream", None)
                if stream in (sys.stderr, sys.stdout):
                    litellm_logger.removeHandler(handler)
        if file_handler not in litellm_logger.handlers:
            litellm_logger.addHandler(file_handler)
        litellm_logger.propagate = False

    return file_handler


def configure_litellm_debug(
    enabled: bool,
    *,
    log_file: Path | str | None = None,
) -> None:
    """Enable verbose LiteLLM logging, optionally redirected to a log file."""
    global _litellm_debug_enabled, _litellm_file_handler
    if enabled:
        if _litellm_debug_enabled:
            return
        litellm.set_verbose = True
        litellm.suppress_debug_info = False
        litellm._turn_on_debug()
        os.environ["LITELLM_LOG"] = "DEBUG"
        if log_file is not None:
            path = Path(log_file)
            _litellm_file_handler = _redirect_litellm_loggers_to_file(path)
            logger.info("LiteLLM debug 日志写入: %s", path.resolve())
        _litellm_debug_enabled = True
        return

    litellm.set_verbose = False
    litellm.suppress_debug_info = True
    if os.environ.get("LITELLM_LOG", "").upper() == "DEBUG":
        os.environ["LITELLM_LOG"] = "ERROR"
    _litellm_debug_enabled = False


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str

    def to_openai_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class ChatResponse:
    content: str = ""
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class StreamChunk:
    thinking: str = ""
    content: str = ""
    tool_calls_delta: list[dict] = field(default_factory=list)
    finish_reason: str | None = None


def _is_retryable_llm_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "connection error" in msg or "timeout" in msg or "temporarily unavailable" in msg


class LiteLLMClient:
    def __init__(self, config: LLMConfig, override: dict | None = None) -> None:
        self.config = config
        self.override = override or {}
        debug = bool(self.override.get("debug", config.debug))
        log_file = self.override.get("debug_log", config.debug_log)
        configure_litellm_debug(debug, log_file=log_file if debug else None)

    async def _acompletion(self, **kwargs: Any) -> Any:
        retries = 3
        last_exc: BaseException | None = None
        for attempt in range(retries):
            try:
                return await litellm.acompletion(**kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt >= retries - 1 or not _is_retryable_llm_error(exc):
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))
        raise last_exc  # pragma: no cover

    def _prepare_messages(self, messages: list[dict]) -> list[dict]:
        return prepare_messages_for_api(
            messages,
            model=self.override.get("model", self.config.model),
            api_base=self.override.get("api_base", self.config.api_base),
        )

    def _kwargs(self, **extra: Any) -> dict[str, Any]:
        model = self.override.get("model", self.config.model)
        kwargs: dict[str, Any] = {
            "model": model,
            "temperature": self.override.get("temperature", self.config.temperature),
            "max_tokens": self.override.get("max_tokens", self.config.max_tokens),
            "timeout": self.override.get("timeout", self.config.timeout),
        }
        api_base = self.override.get("api_base", self.config.api_base)
        api_key = self.override.get("api_key", self.config.api_key)
        if api_base:
            kwargs["api_base"] = api_base
        if api_key:
            kwargs["api_key"] = api_key
        kwargs.update(extra)
        return kwargs

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        call_kwargs = self._kwargs(**kwargs)
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"
        response = await self._acompletion(
            messages=self._prepare_messages(messages),
            **call_kwargs,
        )
        msg = response.choices[0].message
        tool_calls = self._parse_tool_calls(msg)
        thinking = getattr(msg, "reasoning_content", None) or getattr(msg, "thinking", "") or ""
        content = msg.content or ""
        return ChatResponse(content=content, thinking=thinking or "", tool_calls=tool_calls)

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        call_kwargs = self._kwargs(stream=True, **kwargs)
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"
        stream = await self._acompletion(
            messages=self._prepare_messages(messages),
            **call_kwargs,
        )
        tool_call_acc: dict[int, dict] = {}
        async for chunk in stream:
            choice = chunk.choices[0]
            delta = choice.delta
            thinking = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "thinking", None)
                or ""
            )
            content = delta.content or ""
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_call_acc:
                        tool_call_acc[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_call_acc[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_call_acc[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_call_acc[idx]["arguments"] += tc.function.arguments
            yield StreamChunk(
                thinking=thinking or "",
                content=content or "",
                tool_calls_delta=[],
                finish_reason=choice.finish_reason,
            )
        if tool_call_acc:
            yield StreamChunk(
                tool_calls_delta=[
                    {
                        "id": v["id"] or f"call_{uuid.uuid4().hex[:24]}",
                        "type": "function",
                        "function": {"name": v["name"], "arguments": v["arguments"]},
                    }
                    for v in tool_call_acc.values()
                ],
                finish_reason="tool_calls",
            )

    async def summarize(self, messages: list[dict], instruction: str) -> str:
        prompt_messages = list(messages) + [{"role": "user", "content": instruction}]
        resp = await self.chat(prompt_messages)
        return resp.content

    def _parse_tool_calls(self, msg: Any) -> list[ToolCall]:
        if not getattr(msg, "tool_calls", None):
            return []
        result = []
        for tc in msg.tool_calls:
            fn = tc.function
            result.append(
                ToolCall(
                    id=tc.id,
                    name=fn.name,
                    arguments=fn.arguments if isinstance(fn.arguments, str) else json.dumps(fn.arguments),
                )
            )
        return result
