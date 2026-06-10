"""FastAPI application factory with Web UI."""

from __future__ import annotations

from pathlib import Path

from local_agent.api.routes import agents, artifacts, chat, config, skills, threads, uploads


def create_app():
    """
    Factory for the Local Agent API + Web UI.
    Requires optional [api] dependencies: pip install local-agent[api]
    """
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as e:
        raise ImportError(
            "API 模块需要安装可选依赖: pip install local-agent[api]"
        ) from e

    from local_agent.cli.context import get_settings

    settings = get_settings()
    app = FastAPI(title="Local Agent", version="0.1.0")

    origins = settings.api.cors_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    app.include_router(agents.router)
    app.include_router(threads.router)
    app.include_router(chat.router)
    app.include_router(skills.router)
    app.include_router(artifacts.router)
    app.include_router(uploads.router)
    app.include_router(config.router)

    webui_dir = Path(__file__).resolve().parent.parent / "webui"
    if webui_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=webui_dir), name="webui-assets")

        @app.get("/")
        async def index():
            return FileResponse(webui_dir / "index.html")

    return app
