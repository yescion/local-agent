"""Memory debug commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from local_agent.cli.context import get_manager, get_session
from local_agent.storage.repositories.memory_repo import MemoryRepository

console = Console()

MEMORY_HELP = """查看长期记忆（调试）。

与 agent history 不同：history 展示 L0 原始对话，memory 展示 LLM 异步提取的结构化记忆。

  L1  原子记忆（fact / preference / constraint / conclusion）
  L2  场景聚合块（多轮 L1 归纳）

Agent 参数支持 agent list 中的序号或 UUID（与 chat --agent 相同）。

示例:
  local-agent memory show 11
  local-agent memory show 11 --layer L2
  local-agent memory search 11 沙盒
"""

app = typer.Typer(help=MEMORY_HELP, no_args_is_help=True)


def _resolve_agent_id(ref: str) -> str:
    manager = get_manager()
    agent = manager.resolve_agent(ref)
    if not agent:
        console.print(f"[red]未找到 Agent: {ref}（运行 agent list 查看序号）[/red]")
        raise typer.Exit(1)
    return agent.id


@app.command(
    "show",
    help="列出指定 Agent 的 L1 原子记忆，或 --layer L2 查看场景聚合。",
)
def show_memory(
    agent: str = typer.Argument(..., help="Agent 序号或 ID（agent list 查看）"),
    layer: str = typer.Option("L1", "--layer", help="记忆层：L1（原子）或 L2（场景）"),
) -> None:
    agent_id = _resolve_agent_id(agent)
    session = get_session()
    repo = MemoryRepository(session)
    if layer == "L1":
        atoms = repo.list_atoms(agent_id)
        table = Table(title=f"L1 Atoms ({len(atoms)})")
        table.add_column("Type")
        table.add_column("Content")
        table.add_column("Confidence")
        for a in atoms:
            table.add_row(a.type, a.content[:80], str(a.confidence))
        console.print(table)
        if not atoms:
            console.print(
                "[dim]暂无 L1 记忆（对话过短、尚未提取或无可提取内容时为空）。\n"
                f"查看原始对话: agent history show 1 --agent {agent}[/dim]"
            )
    elif layer == "L2":
        scenarios = repo.list_scenarios(agent_id)
        if not scenarios:
            console.print("[dim]暂无 L2 场景聚合（每 N 轮对话后自动生成）。[/dim]")
        for s in scenarios:
            console.print(f"[bold]{s.title}[/bold]: {s.summary}")
    else:
        console.print(f"[red]未知 layer: {layer}（仅支持 L1 或 L2）[/red]")
        raise typer.Exit(1)
    session.close()


@app.command(
    "search",
    help="在指定 Agent 的 L1 原子记忆中全文搜索（BM25）。",
)
def search_memory(
    agent: str = typer.Argument(..., help="Agent 序号或 ID（agent list 查看）"),
    query: str = typer.Argument(..., help="搜索关键词"),
) -> None:
    agent_id = _resolve_agent_id(agent)
    session = get_session()
    repo = MemoryRepository(session)
    atoms = repo.search_atoms(agent_id, query)
    if not atoms:
        console.print(f"[dim]未找到匹配「{query}」的 L1 记忆。[/dim]")
    for a in atoms:
        if a:
            console.print(f"[{a.type}] {a.content}")
    session.close()
