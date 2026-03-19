"""Background task manager for long-running operations (research cycles, attack scans)."""

from __future__ import annotations

import asyncio
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


class TaskInfo:
    """Tracks the state of a background task."""

    __slots__ = (
        "task_id", "status", "result", "error",
        "started_at", "completed_at", "_asyncio_task",
    )

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.status: str = "pending"
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self._asyncio_task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TaskManager:
    """Simple in-memory task manager for background operations."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskInfo] = {}

    def submit(self, coro: Any) -> TaskInfo:
        """Submit a coroutine to run in the background. Returns TaskInfo."""
        task_id = uuid.uuid4().hex[:12]
        info = TaskInfo(task_id)
        info.status = "running"
        info.started_at = datetime.now(timezone.utc)

        async def _wrapper() -> None:
            try:
                result = await coro
                info.result = result
                info.status = "completed"
            except Exception as exc:
                info.error = f"{type(exc).__name__}: {exc}"
                info.status = "failed"
            finally:
                info.completed_at = datetime.now(timezone.utc)

        info._asyncio_task = asyncio.create_task(_wrapper())
        self._tasks[task_id] = info
        return info

    def get(self, task_id: str) -> Optional[TaskInfo]:
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> list[TaskInfo]:
        tasks = sorted(
            self._tasks.values(),
            key=lambda t: t.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return tasks[:limit]
