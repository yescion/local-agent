"""Web UI server command."""

from __future__ import annotations

import typer
from rich.console import Console

from local_agent.cli.context import get_settings

console = Console()

WEB_HELP = """启动 Web UI 与 API 服务。

在浏览器中打开显示的地址即可使用图形界面：
  - 历史会话列表与删除
  - 对话记录（向上滚动加载更早消息）
  - 会话文件区与文件预览
  - 全局配置与会话内配置（人设、技能限制）
  - 技能管理

需要先安装 API 依赖: pip install local-agent[api]
"""

app = typer.Typer(help=WEB_HELP, invoke_without_command=True)


@app.callback()
def serve(
    host: str | None = typer.Option(None, "--host", "-H", help="监听地址"),
    port: int | None = typer.Option(None, "--port", "-p", help="监听端口"),
    reload: bool = typer.Option(False, "--reload", help="开发模式热重载"),
) -> None:
    """启动 Web UI 服务。"""
    try:
        import uvicorn
    except ImportError as e:
        console.print("[red]请先安装 API 依赖: pip install local-agent[api][/red]")
        raise typer.Exit(1) from e

    settings = get_settings()
    bind_host = host or settings.api.host
    bind_port = port or settings.api.port
    console.print(f"[green]Web UI:[/green] http://{bind_host}:{bind_port}/")
    uvicorn.run(
        "local_agent.api.app:create_app",
        factory=True,
        host=bind_host,
        port=bind_port,
        reload=reload,
    )
