"""Artifact management commands."""

from __future__ import annotations

import typer
from rich.console import Console

from local_agent.cli.artifacts_display import print_artifact_list
from local_agent.cli.context import get_manager

console = Console()

ARTIFACT_HELP = """Agent 产物文件管理。

产物是 Agent 在对话或工具执行中生成的文件（报告、代码、图表等），
存储在 data/artifacts/ 下，按 Agent 和会话归类。

示例:
  local-agent artifact list --agent 3
  local-agent artifact list --agent 3 --thread 1
"""

app = typer.Typer(help=ARTIFACT_HELP, no_args_is_help=True)


@app.command("list", help="列出指定 Agent（及可选会话）的产物文件。")
def list_artifacts(
    agent: str = typer.Option(..., "--agent", "-a", help="Agent 序号或 ID（agent list 查看）"),
    thread: str | None = typer.Option(
        None, "--thread", "-t", help="会话序号或 ID（省略则列出该 Agent 全部产物）"
    ),
) -> None:
    manager = get_manager()
    agent_obj = manager.resolve_agent(agent)
    if not agent_obj:
        console.print(f"[red]未找到 Agent: {agent}[/red]")
        raise typer.Exit(1)

    thread_id: str | None = None
    title = f"{agent_obj.name} 的全部产物"
    if thread:
        thread_obj = manager.resolve_thread(agent_obj.id, thread)
        if not thread_obj:
            console.print(f"[red]未找到会话: {thread}[/red]")
            raise typer.Exit(1)
        thread_id = thread_obj.id
        thread_title = thread_obj.title or "(无标题)"
        title = f"{agent_obj.name} · {thread_title}"

    artifacts = manager.list_artifacts(agent_obj.id, thread_id=thread_id)
    print_artifact_list(console, artifacts, title=title)
