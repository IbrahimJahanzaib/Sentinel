"""Async DB query functions for reporting."""

from __future__ import annotations

from sqlalchemy import select

from sentinel.db.connection import get_session
from sentinel.db.models import Cycle, Failure, Hypothesis, Intervention
from sentinel.taxonomy.failure_types import Severity


def parse_severity_filter(raw: str) -> Severity:
    """Parse a severity filter string like "S2+" into a Severity enum.

    The trailing '+' is stripped — caller uses >= comparison.
    """
    return Severity(raw.rstrip("+"))


async def get_cycles(limit: int = 50) -> list[Cycle]:
    """Return recent Cycle rows ordered by started_at descending."""
    async with get_session() as session:
        result = await session.execute(
            select(Cycle).order_by(Cycle.started_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def get_failures(
    *,
    min_severity: str | None = None,
    failure_class: str | None = None,
    cycle_id: str | None = None,
) -> list[Failure]:
    """Return Failure rows with optional filters."""
    stmt = select(Failure)

    if cycle_id is not None:
        stmt = stmt.where(Failure.cycle_id == cycle_id)
    if failure_class is not None:
        stmt = stmt.where(Failure.failure_class == failure_class)

    async with get_session() as session:
        result = await session.execute(stmt.order_by(Failure.created_at.desc()))
        rows = list(result.scalars().all())

    if min_severity is not None:
        threshold = parse_severity_filter(min_severity)
        rows = [f for f in rows if Severity(f.severity) >= threshold]

    return rows


async def get_hypotheses(
    *,
    status: str | None = None,
    cycle_id: str | None = None,
) -> list[Hypothesis]:
    """Return Hypothesis rows with optional filters."""
    stmt = select(Hypothesis)

    if cycle_id is not None:
        stmt = stmt.where(Hypothesis.cycle_id == cycle_id)
    if status is not None:
        stmt = stmt.where(Hypothesis.status == status)

    async with get_session() as session:
        result = await session.execute(stmt.order_by(Hypothesis.created_at.desc()))
        return list(result.scalars().all())


async def get_interventions(
    *,
    cycle_id: str | None = None,
) -> list[Intervention]:
    """Return Intervention rows with optional cycle filter."""
    stmt = select(Intervention)

    if cycle_id is not None:
        stmt = stmt.where(Intervention.cycle_id == cycle_id)

    async with get_session() as session:
        result = await session.execute(stmt.order_by(Intervention.created_at.desc()))
        return list(result.scalars().all())
