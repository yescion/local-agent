"""Skill management commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from local_agent.cli.context import get_manager, get_skill_registry

console = Console()

SKILL_HELP = """技能（Skill）管理。

技能是带指令的 Markdown 能力包，Agent 可通过 manage_skills 工具按需加载。
内置技能在 skills/_builtin/，自定义技能放 skills/custom/。

示例:
  local-agent skill list
  local-agent skill show web_search
  local-agent skill scan
  local-agent skill register ./skills/custom/my_skill
  local-agent skill reload --all
  local-agent chat --new --skills web_search,daytona_sandbox
"""

app = typer.Typer(help=SKILL_HELP, no_args_is_help=True)


@app.command("list", help="列出所有已注册技能（含 ID、描述和启用状态）。")
def list_skills() -> None:
    registry = get_skill_registry()
    skills = registry.list_skills(enabled_only=False)
    table = Table(title="Skills")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("Enabled")
    for s in skills:
        table.add_row(s.id, s.name, s.description[:50], str(s.enabled))
    console.print(table)


@app.command("register", help="注册技能目录或 SKILL.md 文件到技能中心。")
def register_skill(
    path: Path = typer.Argument(..., help="技能目录（含 SKILL.md）或 SKILL.md 文件路径"),
) -> None:
    registry = get_skill_registry()
    skill_path = path / "SKILL.md" if path.is_dir() else path
    meta = registry.register(skill_path)
    console.print(f"[green]已注册技能[/green] {meta.id} — {meta.name}")


@app.command("unregister", help="从技能中心注销指定技能（不删除磁盘文件）。")
def unregister_skill(skill_id: str = typer.Argument(..., help="技能 ID（skill list 查看）")) -> None:
    registry = get_skill_registry()
    registry.unregister(skill_id)
    console.print(f"[green]已注销技能[/green] {skill_id}")


@app.command("reload", help="重新加载技能内容（修改 SKILL.md 后使用）。")
def reload_skills(
    all_skills: bool = typer.Option(False, "--all", help="扫描目录并重载全部技能"),
    skill_id: str | None = typer.Option(None, "--id", help="仅重载指定技能 ID"),
) -> None:
    manager = get_manager()
    if all_skills:
        count = manager.reload_skills()
        console.print(f"[green]已扫描并重载 {count} 个技能[/green]")
    elif skill_id:
        if not manager.reload_skill(skill_id):
            console.print(f"[red]未找到技能 {skill_id}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]已重载技能[/green] {skill_id}")
    else:
        console.print("[red]请指定 --all 或 --id[/red]")


@app.command("show", help="查看技能的完整元数据和指令内容。")
def show_skill(skill_id: str = typer.Argument(..., help="技能 ID（skill list 查看）")) -> None:
    registry = get_skill_registry()
    meta = registry.get_skill(skill_id)
    if not meta:
        console.print(f"[red]未找到技能 {skill_id}[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{meta.name}[/bold] (v{meta.version})")
    console.print(meta.content)


@app.command("scan", help="扫描配置的技能目录（skills/_builtin、skills/custom）并注册。")
def scan_skills() -> None:
    registry = get_skill_registry()
    count = registry.scan_directories()
    console.print(f"[green]扫描完成，共 {count} 个技能[/green]")
