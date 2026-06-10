"""Agent management commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from local_agent.agent.models import Persona
from local_agent.cli.artifacts_display import format_artifact_summary
from local_agent.cli.context import get_manager, get_session
from local_agent.cli.history_display import print_conversation_history
from local_agent.storage.models import format_local_datetime
from local_agent.storage.repositories.message_repo import MessageRepository, ThreadRepository

console = Console()

AGENT_HELP = """Agent 实例管理。

每个 Agent 是独立实例，拥有自己的人设、技能绑定和会话线程。
列表序号 #1 为最新创建，与 chat --agent、memory show 等命令通用。

示例:
  local-agent agent list
  local-agent agent create --name 研究员 --skills web_search
  local-agent agent delete 5
  local-agent agent history show 1 --agent 3
"""

HISTORY_HELP = """会话记录（L0 原始对话）查看与导入导出。

与 memory 不同：history 展示完整消息轨迹，memory 展示 LLM 提取的结构化记忆。
会话序号在该 Agent 的线程列表中指定（REPL 内 /history 可查看）。

示例:
  local-agent agent history show 1 --agent 3
  local-agent agent history show 1 --agent 3 --limit 5
  local-agent agent history export <thread-uuid> -o backup.json
  local-agent agent history import <thread-uuid> backup.json
"""

app = typer.Typer(help=AGENT_HELP, no_args_is_help=True)
history_app = typer.Typer(help=HISTORY_HELP, no_args_is_help=True)
app.add_typer(history_app, name="history")


@app.command("create", help="创建新 Agent 实例，可指定名称、人设和技能。")
def create_agent(
    name: str = typer.Option(..., "--name", "-n", help="Agent 显示名称"),
    persona: str = typer.Option(
        '{"role":"通用助手","tone":"简洁专业"}',
        "--persona",
        help='人设 JSON，如 {"role":"研究员","tone":"严谨"}',
    ),
    skills: str = typer.Option(
        "", "--skills", help="绑定的技能 ID，逗号分隔（skill list 查看可用技能）"
    ),
) -> None:
    manager = get_manager()
    persona_obj = Persona.model_validate(json.loads(persona))
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
    agent = manager.create_agent(name=name, persona=persona_obj, skills=skill_list)
    console.print(f"[green]已创建 Agent[/green] {agent.name} (序号: 1)")


@app.command("list", help="列出所有 Agent，含摘要、轮次、技能和产物概览。")
def list_agents() -> None:
    manager = get_manager()
    agents = manager.list_agents_with_preview()
    table = Table(title="Agents（按创建时间倒序，最新为 #1）")
    table.add_column("#", style="bold cyan", justify="right")
    table.add_column("Name")
    table.add_column("摘要", max_width=50, overflow="ellipsis")
    table.add_column("轮次", justify="right")
    table.add_column("最近活跃")
    table.add_column("产物", max_width=30, overflow="ellipsis")
    table.add_column("Skills")
    for i, (a, preview) in enumerate(agents, start=1):
        last_active = format_local_datetime(
            preview.last_active if preview.last_active else a.created_at
        )
        turns = str(preview.turn_count) if preview.turn_count else "—"
        artifact_summary = manager.get_artifact_summary(agent_id=a.id)
        artifacts = format_artifact_summary(
            artifact_summary.count, artifact_summary.names
        )
        table.add_row(
            str(i),
            a.name,
            preview.preview,
            turns,
            last_active,
            artifacts,
            ", ".join(a.skills) or "—",
        )
    console.print(table)
    console.print(
        "[dim]继续对话: chat --agent 1  |  查看记录: agent history show 1 --agent 1[/dim]"
    )


@app.command("delete", help="删除指定 Agent 及其全部会话、记忆和产物。")
def delete_agent(ref: str = typer.Argument(..., help="Agent 序号或 ID（agent list 查看）")) -> None:
    manager = get_manager()
    agent = manager.resolve_agent(ref)
    if not agent:
        console.print(f"[red]未找到 Agent: {ref}[/red]")
        raise typer.Exit(1)
    if manager.delete_agent(agent.id):
        console.print(f"[green]已删除 Agent #{ref} — {agent.name}[/green]")
    else:
        console.print(f"[red]删除失败: {agent.name}[/red]")
        raise typer.Exit(1)


def _resolve_agent_id(agent: str | None) -> str:
    manager = get_manager()
    if agent:
        resolved = manager.resolve_agent(agent)
        if not resolved:
            console.print(f"[red]未找到 Agent: {agent}[/red]")
            raise typer.Exit(1)
        return resolved.id
    default = manager.resolve_default_agent()
    if not default:
        console.print("[red]无可用 Agent[/red]")
        raise typer.Exit(1)
    return default.id


@history_app.command("show", help="查看指定会话的完整对话记录（L0）。")
def show_history(
    thread: str = typer.Argument(..., help="会话序号或 ID（该 Agent 下的线程编号）"),
    agent: str | None = typer.Option(
        None, "--agent", "-a", help="Agent 序号或 ID（省略则用最近活跃的 Agent）"
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="仅显示最近 N 轮用户/助手往返（默认全部）"
    ),
) -> None:
    manager = get_manager()
    agent_id = _resolve_agent_id(agent)
    matched = manager.resolve_thread(agent_id, thread)
    if not matched:
        console.print(f"[red]未找到会话: {thread}[/red]")
        raise typer.Exit(1)

    session = get_session()
    try:
        messages = MessageRepository(session).load_messages(matched.id)
    finally:
        session.close()

    title = matched.title or "(无标题)"
    preview = manager.get_thread_preview(matched.id)
    print_conversation_history(
        console,
        messages,
        limit=limit,
        title=f"{title} · {preview.turn_count} 轮",
    )


@history_app.command("export", help="将会话消息导出为 JSON 文件（备份或迁移）。")
def export_history(
    thread_id: str = typer.Argument(..., help="会话线程 UUID（非列表序号）"),
    output: Path = typer.Option(
        Path("history.json"), "--output", "-o", help="输出文件路径（默认 history.json）"
    ),
) -> None:
    session = get_session()
    try:
        data = MessageRepository(session).export_json(thread_id)
    finally:
        session.close()
    output.write_text(data, encoding="utf-8")
    console.print(f"[green]已导出到 {output}[/green]")


@history_app.command("import", help="从 JSON 文件导入消息到已有会话线程。")
def import_history(
    thread_id: str = typer.Argument(..., help="目标会话线程 UUID（须已存在）"),
    input_file: Path = typer.Argument(..., help="agent history export 生成的 JSON 文件"),
) -> None:
    session = get_session()
    try:
        if not ThreadRepository(session).get(thread_id):
            console.print(f"[red]未找到线程 {thread_id}[/red]")
            raise typer.Exit(1)
        count = MessageRepository(session).import_json(
            thread_id, input_file.read_text(encoding="utf-8")
        )
    finally:
        session.close()
    console.print(f"[green]已导入 {count} 条消息[/green]")
