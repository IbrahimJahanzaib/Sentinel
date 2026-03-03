"""Audit trail — immutable log of all Sentinel actions."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select

from .connection import get_session
from .models import AuditEntry


async def log_event(
    event_type: str,
    *,
    actor: str = "sentinel",
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    mode: str = "lab",
) -> None:
    """Write an immutable audit entry.

    Parameters
    ----------
    event_type:
        What happened (e.g. "experiment.approved", "failure.classified", "cycle.started").
    actor:
        Who initiated the action ("sentinel", "human", or a user identifier).
    entity_type / entity_id:
        What the action was performed on (e.g. entity_type="experiment", entity_id="abc123").
    details:
        Arbitrary structured context for the event.
    mode:
        Operating mode at the time of the event.
    """
    entry = AuditEntry(
        event_type=event_type,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
        mode=mode,
    )
    async with get_session() as session:
        session.add(entry)


async def get_audit_log(
    event_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 100,
) -> list[AuditEntry]:
    """Query the audit log."""
    async with get_session() as session:
        stmt = select(AuditEntry).order_by(AuditEntry.timestamp.desc()).limit(limit)
        if event_type:
            stmt = stmt.where(AuditEntry.event_type == event_type)
        if entity_id:
            stmt = stmt.where(AuditEntry.entity_id == entity_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())
