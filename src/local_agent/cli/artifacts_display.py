"""Artifact list display helpers."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from local_agent.artifacts.models import Artifact
from local_agent.storage.models import format_local_datetime


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "—"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_artifact_summary(count: int, names: list[str]) -> str:
    if count <= 0:
        return "—"
    if not names:
        return str(count)
    label = "、".join(names)
    if count > len(names):
        label += f" 等 {count} 个"
    return label


def print_artifact_list(
    console: Console,
    artifacts: list[Artifact],
    *,
    title: str | None = None,
) -> None:
    if title:
        console.print(f"\n[cyan][ARTIFACTS][/cyan] {title}")

    if not artifacts:
        console.print("[dim]（暂无产物）[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", style="bold")
    table.add_column("名称")
    table.add_column("大小", justify="right")
    table.add_column("工具")
    table.add_column("路径", overflow="ellipsis", max_width=40)
    table.add_column("创建时间")

    for i, artifact in enumerate(artifacts, start=1):
        table.add_row(
            str(i),
            artifact.name,
            _format_size(artifact.size_bytes),
            artifact.tool_name or "—",
            str(artifact.path),
            format_local_datetime(artifact.created_at),
        )
    console.print(table)
