"""Research cycles API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from sentinel.db.connection import get_session
from sentinel.db.models import Cycle, Failure, Hypothesis, Intervention

router = APIRouter()


@router.get("/cycles")
async def list_cycles(limit: int = 20, offset: int = 0):
    """List all research cycles, most recent first."""
    async with get_session() as session:
        result = await session.execute(
            select(Cycle).order_by(Cycle.started_at.desc()).offset(offset).limit(limit)
        )
        cycles = result.scalars().all()
        return [
            {
                "id": c.id,
                "target": c.target_description,
                "focus": c.focus,
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "ended_at": c.ended_at.isoformat() if c.ended_at else None,
                "hypotheses_generated": c.hypotheses_generated,
                "hypotheses_confirmed": c.hypotheses_confirmed,
                "experiments_run": c.experiments_run,
                "failures_found": c.failures_found,
                "mode": c.mode,
                "total_cost_usd": c.total_cost_usd,
            }
            for c in cycles
        ]


@router.get("/cycles/{cycle_id}")
async def get_cycle(cycle_id: str):
    """Get full details of a research cycle."""
    async with get_session() as session:
        result = await session.execute(
            select(Cycle).where(Cycle.id == cycle_id)
        )
        cycle = result.scalar_one_or_none()
        if not cycle:
            raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")

        hyp_result = await session.execute(
            select(Hypothesis).where(Hypothesis.cycle_id == cycle_id)
        )
        hypotheses = hyp_result.scalars().all()

        fail_result = await session.execute(
            select(Failure).where(Failure.cycle_id == cycle_id)
        )
        failures = fail_result.scalars().all()

        int_result = await session.execute(
            select(Intervention).where(Intervention.cycle_id == cycle_id)
        )
        interventions = int_result.scalars().all()

        return {
            "cycle": {
                "id": cycle.id,
                "target": cycle.target_description,
                "focus": cycle.focus,
                "mode": cycle.mode,
                "started_at": cycle.started_at.isoformat() if cycle.started_at else None,
                "ended_at": cycle.ended_at.isoformat() if cycle.ended_at else None,
                "total_cost_usd": cycle.total_cost_usd,
            },
            "hypotheses": [
                {
                    "id": h.id,
                    "description": h.description,
                    "failure_class": h.failure_class,
                    "expected_severity": h.expected_severity,
                    "status": h.status,
                }
                for h in hypotheses
            ],
            "failures": [
                {
                    "id": f.id,
                    "failure_class": f.failure_class,
                    "severity": f.severity,
                    "failure_rate": f.failure_rate,
                    "evidence": f.evidence[:300] if f.evidence else "",
                }
                for f in failures
            ],
            "interventions": [
                {
                    "id": i.id,
                    "type": i.type,
                    "description": i.description,
                    "validation_status": i.validation_status,
                }
                for i in interventions
            ],
        }
