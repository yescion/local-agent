"""Interactive REPL."""

from __future__ import annotations

import asyncio
import queue

from rich.console import Console
from rich.prompt import Prompt

from local_agent.agent.manager import AgentManager
from local_agent.cli.history_display import print_conversation_history
from local_agent.cli.slash import SlashCommandHandler
_USER_PROMPT = "\n[bold]You[/bold]"


def _print_reload_notice(console: Console, count: int) -> None:
    console.print(
        f"\n[dim cyan][SYSTEM] 技能文件变更，已自动热重载 {count} 个技能[/dim cyan]"
    )


def _reprompt_user(console: Console) -> None:
    """Re-show input prompt after async system output interrupted Prompt.ask."""
    console.print("[bold]You[/bold]: ", end="")
    console.file.flush()


async def run_repl(
    manager: AgentManager,
    agent_id: str,
    thread_id: str | None = None,
) -> None:
    console = Console()
    runtime = manager.get_or_create_runtime(agent_id, thread_id, console)
    slash = SlashCommandHandler(runtime, manager, console)
    reload_notices: queue.Queue[int] = queue.Queue()

    if manager.settings.skills.auto_reload:

        def _on_skill_change(count: int) -> None:
            reload_notices.put(count)
            _print_reload_notice(console, count)
            _reprompt_user(console)

        manager.add_skill_reload_listener(_on_skill_change)

    threads = manager.list_threads(agent_id)
    thread = next((t for t in threads if t.id == runtime.thread_id), None)
    thread_title = thread.title if thread else "(无标题)"
    preview = manager.get_thread_preview(runtime.thread_id)

    console.print(
        f"[bold green]Local Agent REPL[/bold green] — {runtime.agent.name} "
        f"(输入 /help 查看命令, /history 查看记录, quit 退出)"
    )
    if manager.settings.skills.auto_reload:
        console.print("[dim]技能热重载已开启（修改 SKILL.md / tools.py 后自动生效）[/dim]")
    if preview.turn_count > 0:
        console.print(
            f"[dim]继续会话 «{thread_title}» · {preview.turn_count} 轮"
            f" · 输入 /history 查看完整记录[/dim]"
        )
        print_conversation_history(
            console,
            runtime.messages,
            limit=5,
            truncate=160,
            title="最近对话",
        )

    while True:
        while not reload_notices.empty():
            try:
                reload_notices.get_nowait()
            except queue.Empty:
                break

        try:
            user_input = Prompt.ask(_USER_PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break

        if user_input.startswith("/"):
            if await slash.handle(user_input):
                if slash.should_exit:
                    break
                continue

        try:
            await runtime.chat_turn(user_input, stream=True)
            console.print()
        except Exception as e:
            console.print(f"[red]错误: {e}[/red]")

    await runtime.drain_memory_tasks()
    runtime.background_loop.stop()
    from local_agent.jobs.service import stop_job_scheduler

    stop_job_scheduler()
