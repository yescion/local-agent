"""Chat commands."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from local_agent.agent.models import Persona
from local_agent.cli.context import get_manager
from local_agent.cli.repl import run_repl

console = Console()

CHAT_HELP = """与 Agent 交互对话。

默认进入 REPL 多轮对话；加 -m 则单轮问答后退出。
未指定 --agent 时自动继续最近活跃的 Agent；无 Agent 时自动新建。

REPL 内可用斜杠命令（不走 LLM）: /help /skills /tools /history /artifacts 等。

示例:
  local-agent chat
  local-agent chat --new --skills web_search,daytona_sandbox
  local-agent chat --agent 3
  local-agent chat --agent 3 --thread 2
  local-agent chat --agent 1 -m "查询上证指数"
"""


def chat(
    agent: str | None = typer.Option(
        None, "--agent", "-a", help="Agent 序号或 ID（agent list 查看，#1 为最新）"
    ),
    message: str | None = typer.Option(
        None, "--message", "-m", help="单轮消息（省略则进入 REPL 多轮对话）"
    ),
    new_agent: bool = typer.Option(
        False, "--new", help="新建 Agent 并开始对话（与 --agent 互斥时优先新建）"
    ),
    name: str = typer.Option("临时助手", "--name", help="--new 时使用的 Agent 名称"),
    skills: str = typer.Option(
        "", "--skills", help="--new 时绑定的技能 ID，逗号分隔（先 skill list 查看）"
    ),
    thread: str | None = typer.Option(
        None, "--thread", help="会话序号或 ID（继续指定会话；省略则新建会话）"
    ),
) -> None:
    manager = get_manager()
    agent_id: str | None = None
    thread_id: str | None = None

    if agent:
        resolved = manager.resolve_agent(agent)
        if not resolved:
            console.print(f"[red]未找到 Agent: {agent}（运行 agent list 查看序号）[/red]")
            raise typer.Exit(1)
        agent_id = resolved.id

    if new_agent:
        skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
        created = manager.create_agent(name=name, persona=Persona(), skills=skill_list)
        agent_id = created.id
        console.print(f"[green]已创建 Agent[/green] {created.name} (序号: 1)")
    elif not agent_id:
        default = manager.resolve_default_agent()
        if default:
            agent_id = default.id
            agents = manager.list_agents()
            idx = next((i for i, a in enumerate(agents, start=1) if a.id == agent_id), "?")
            console.print(
                f"[dim]继续 Agent #{idx} «{default.name}»"
                f"（新建请用 --new，切换请用 --agent <序号>）[/dim]"
            )
        else:
            skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
            created = manager.create_agent(name=name, persona=Persona(), skills=skill_list)
            agent_id = created.id
            console.print(f"[green]已创建 Agent[/green] {created.name} (序号: 1)")

    if thread:
        assert agent_id is not None
        resolved_thread = manager.resolve_thread(agent_id, thread)
        if not resolved_thread:
            console.print(f"[red]未找到会话: {thread}[/red]")
            raise typer.Exit(1)
        thread_id = resolved_thread.id

    if message:
        reply = asyncio.run(manager.chat(agent_id, message, thread_id, console))
        console.print(reply)
    else:
        asyncio.run(run_repl(manager, agent_id, thread_id))
