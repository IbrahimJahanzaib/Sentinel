"""FastAPI dashboard application factory and runner."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sentinel.dashboard.routes import (
    api_attacks,
    api_benchmarks,
    api_failures,
    api_research,
    api_settings,
    websocket,
)
from sentinel.db.connection import close_db, init_db

DASHBOARD_DIR = Path(__file__).parent


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


def create_dashboard_app() -> FastAPI:
    """Create and configure the dashboard FastAPI application."""
    app = FastAPI(title="Sentinel Dashboard", docs_url="/api/docs", lifespan=_lifespan)

    # Static files
    app.mount("/static", StaticFiles(directory=DASHBOARD_DIR / "static"), name="static")

    # Templates
    templates = Jinja2Templates(directory=DASHBOARD_DIR / "templates")

    # API routes
    app.include_router(api_research.router, prefix="/api", tags=["research"])
    app.include_router(api_failures.router, prefix="/api", tags=["failures"])
    app.include_router(api_benchmarks.router, prefix="/api", tags=["benchmarks"])
    app.include_router(api_attacks.router, prefix="/api", tags=["attacks"])
    app.include_router(api_settings.router, prefix="/api", tags=["settings"])
    app.include_router(websocket.router, tags=["websocket"])

    @app.get("/")
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def run_dashboard(port: int = 8080, host: str = "0.0.0.0") -> None:
    """Run the dashboard with uvicorn."""
    import uvicorn

    app = create_dashboard_app()
    uvicorn.run(app, host=host, port=port)
