"""Failures API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from sentinel.db.connection import get_session
from sentinel.db.models import Failure, Intervention

router = APIRouter()


@router.get("/failures")
async def list_failures(
    severity: Optional[str] = None,
    failure_class: Optional[str] = None,
    cycle_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """List failures with optional filters."""
    async with get_session() as session:
        query = select(Failure).order_by(Failure.created_at.desc())

        if severity:
            query = query.where(Failure.severity == severity)
        if failure_class:
            query = query.where(Failure.failure_class == failure_class)
        if cycle_id:
            query = query.where(Failure.cycle_id == cycle_id)

        result = await session.execute(query.offset(offset).limit(limit))
        failures = result.scalars().all()
        return [
            {
                "id": f.id,
                "experiment_id": f.experiment_id,
                "cycle_id": f.cycle_id,
                "failure_class": f.failure_class,
                "severity": f.severity,
                "failure_rate": f.failure_rate,
                "evidence": f.evidence[:300] if f.evidence else "",
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in failures
        ]


@router.get("/failures/stats")
async def failure_stats():
    """Aggregated failure statistics for dashboard charts."""
    async with get_session() as session:
        total_result = await session.execute(select(func.count(Failure.id)))
        total = total_result.scalar() or 0

        by_class_result = await session.execute(
            select(Failure.failure_class, func.count(Failure.id))
            .group_by(Failure.failure_class)
        )
        by_class = dict(by_class_result.all())

        by_severity_result = await session.execute(
            select(Failure.severity, func.count(Failure.id))
            .group_by(Failure.severity)
        )
        by_severity = dict(by_severity_result.all())

        return {
            "total": total,
            "by_class": by_class,
            "by_severity": by_severity,
        }


@router.get("/failures/{failure_id}")
async def get_failure(failure_id: str):
    """Get full failure details with interventions."""
    async with get_session() as session:
        result = await session.execute(
            select(Failure).where(Failure.id == failure_id)
        )
        failure = result.scalar_one_or_none()
        if not failure:
            raise HTTPException(status_code=404, detail=f"Failure {failure_id} not found")

        int_result = await session.execute(
            select(Intervention).where(Intervention.failure_id == failure_id)
        )
        interventions = int_result.scalars().all()

        return {
            "failure": {
                "id": failure.id,
                "experiment_id": failure.experiment_id,
                "cycle_id": failure.cycle_id,
                "failure_class": failure.failure_class,
                "failure_subtype": failure.failure_subtype,
                "severity": failure.severity,
                "failure_rate": failure.failure_rate,
                "evidence": failure.evidence,
                "sample_failure_output": failure.sample_failure_output,
                "sample_correct_output": failure.sample_correct_output,
                "created_at": failure.created_at.isoformat() if failure.created_at else None,
            },
            "interventions": [
                {
                    "id": i.id,
                    "type": i.type,
                    "description": i.description,
                    "validation_status": i.validation_status,
                    "validation_notes": i.validation_notes,
                    "failure_rate_before": i.failure_rate_before,
                    "failure_rate_after": i.failure_rate_after,
                }
                for i in interventions
            ],
        }
