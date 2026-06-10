"""Stream output with thinking/content separation."""

from __future__ import annotations

from typing import Callable

from local_agent.agent.exceptions import ChatTurnCancelled
from local_agent.llm.litellm_client import LiteLLMClient, ToolCall


async def stream_with_thinking(
    client: LiteLLMClient,
    messages: list[dict],
    tools: list[dict] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_content: Callable[[str], None] | None = None,
    on_thinking_start: Callable[[], None] | None = None,
    on_answer_start: Callable[[], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[str, str, list[ToolCall] | None]:
    """
    Stream chunks: thinking → [思考过程], content → [最终答复].
    Returns (full_content, full_thinking, tool_calls).
    """
    full_content = ""
    full_thinking = ""
    is_thinking = False
    answer_started = False
    tool_calls_raw: list[dict] = []

    async for chunk in client.chat_stream(messages, tools=tools):
        if cancel_check and cancel_check():
            raise ChatTurnCancelled()
        if chunk.thinking:
            if not is_thinking and on_thinking_start:
                on_thinking_start()
            is_thinking = True
            full_thinking += chunk.thinking
            if on_thinking:
                on_thinking(chunk.thinking)
        if chunk.content:
            if is_thinking and not answer_started and on_answer_start:
                on_answer_start()
            is_thinking = False
            answer_started = True
            full_content += chunk.content
            if on_content:
                on_content(chunk.content)
        if chunk.tool_calls_delta:
            tool_calls_raw = chunk.tool_calls_delta

    tool_calls = None
    if tool_calls_raw:
        tool_calls = [
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"],
            )
            for tc in tool_calls_raw
        ]
    return full_content, full_thinking, tool_calls
