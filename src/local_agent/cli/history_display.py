"""Conversation history display helpers for the REPL."""



from __future__ import annotations



from rich.console import Console

from rich.markup import escape



from local_agent.agent.manager import AgentManager

from local_agent.cli.artifacts_display import format_artifact_summary

from local_agent.storage.models import format_local_datetime





def _tool_call_names(message: dict) -> list[str]:

    names: list[str] = []

    for tc in message.get("tool_calls") or []:

        if not isinstance(tc, dict):

            continue

        fn = tc.get("function") or {}

        name = fn.get("name") if isinstance(fn, dict) else None

        if name:

            names.append(name)

    return names





def extract_display_turns(messages: list[dict]) -> list[tuple[str, str]]:

    """Extract user/assistant turns suitable for terminal display."""

    turns: list[tuple[str, str]] = []

    for msg in messages:

        role = msg.get("role")

        if role == "user":

            content = msg.get("content")

            if content:

                turns.append(("You", str(content)))

        elif role == "assistant":

            content = msg.get("content")

            if content:

                turns.append(("Assistant", str(content)))

            elif msg.get("tool_calls"):

                names = _tool_call_names(msg)

                label = ", ".join(names) if names else "工具"

                turns.append(("Assistant", f"[调用了工具: {label}]"))

    return turns





def _truncate(text: str, max_len: int) -> str:

    collapsed = " ".join(text.split())

    if len(collapsed) <= max_len:

        return collapsed

    return collapsed[: max_len - 1] + "…"





def print_conversation_history(

    console: Console,

    messages: list[dict],

    *,

    limit: int | None = None,

    truncate: int | None = None,

    title: str | None = None,

) -> int:

    """Print conversation turns. Returns the number of turns shown."""

    turns = extract_display_turns(messages)

    if limit is not None and limit > 0:

        turns = turns[-limit:]



    if title:

        console.print(f"\n[cyan][HISTORY][/cyan] {title}")



    if not turns:

        console.print("[dim]（暂无对话记录）[/dim]")

        return 0



    shown = 0

    for label, content in turns:

        text = _truncate(content, truncate) if truncate else content

        if label == "You":

            console.print(f"\n[bold]You[/bold]: {escape(text)}")

        else:

            console.print(f"\n[green]Assistant[/green]: {escape(text)}")

        shown += 1

    return shown





def print_thread_list(

    console: Console,

    manager: AgentManager,

    agent_id: str,

    *,

    current_thread_id: str | None = None,

    show_agent_header: bool = False,

    agent_label: str | None = None,

) -> int:

    """Print threads for an agent. Returns the number of threads shown."""

    threads = manager.list_threads(agent_id)

    if not threads:

        return 0



    if show_agent_header and agent_label:

        console.print(f"\n[bold]{agent_label}[/bold]")



    for i, thread in enumerate(threads, start=1):

        title = thread.title or "(无标题)"

        preview = manager.get_thread_preview(thread.id)
        artifact_summary = manager.get_artifact_summary(thread_id=thread.id)
        artifacts_label = ""
        if artifact_summary.count:
            names = format_artifact_summary(
                artifact_summary.count, artifact_summary.names
            )
            artifacts_label = f" · 产物: {names}"
        last_active = format_local_datetime(
            preview.last_active if preview.last_active else thread.updated_at
        )
        current = ""
        if current_thread_id and thread.id == current_thread_id:
            current = " · [bold green]当前[/bold green]"
        console.print(
            f"  #{i} — {title} ({last_active})"
            f" · {preview.turn_count} 轮 · {preview.preview}{artifacts_label}{current}"
        )

    return len(threads)

