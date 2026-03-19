"""FastAPI application factory and lifecycle management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel.config.settings import SentinelSettings, load_settings
from sentinel.db.connection import close_db, init_db

from .tasks import TaskManager

# ---------------------------------------------------------------------------
# Module-level singletons (set during lifespan)
# ---------------------------------------------------------------------------

_settings: Optional[SentinelSettings] = None
_task_mgr: Optional[TaskManager] = None


def _app_settings() -> SentinelSettings:
    if _settings is None:
        raise RuntimeError("App not started — settings not loaded")
    return _settings


def _task_manager() -> TaskManager:
    if _task_mgr is None:
        raise RuntimeError("App not started — task manager not available")
    return _task_mgr


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(
    settings: Optional[SentinelSettings] = None,
    skip_db_init: bool = False,
) -> FastAPI:
    """Create and configure the Sentinel API application.

    Parameters
    ----------
    settings:
        Inject custom settings (useful for testing). Uses load_settings() if omitted.
    skip_db_init:
        Skip database initialization (useful when DB is managed externally).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _settings, _task_mgr

        _settings = settings or load_settings()
        _task_mgr = TaskManager()

        if not skip_db_init:
            await init_db(_settings.database.url, echo=_settings.database.echo)

        yield

        if not skip_db_init:
            await close_db()

        _task_mgr = None
        _settings = None

    app = FastAPI(
        title="Sentinel API",
        description="REST API for the Sentinel autonomous AI reliability research agent.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — permissive defaults, tighten via env in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    from .routes import router
    app.include_router(router, prefix="/api/v1")

    return app
