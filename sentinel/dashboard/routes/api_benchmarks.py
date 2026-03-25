"""Benchmarks API routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from sentinel.db.connection import get_session
from sentinel.db.models import BenchmarkRun, ModelComparison

router = APIRouter()


@router.get("/benchmarks")
async def list_benchmarks(limit: int = 20):
    """List all benchmark runs."""
    async with get_session() as session:
        result = await session.execute(
            select(BenchmarkRun)
            .order_by(BenchmarkRun.started_at.desc())
            .limit(limit)
        )
        runs = result.scalars().all()
        return [
            {
                "id": r.id,
                "model_name": r.model_name,
                "model_provider": r.model_provider,
                "profile": r.profile,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "duration_seconds": r.duration_seconds,
            }
            for r in runs
        ]


@router.get("/benchmarks/comparisons")
async def list_comparisons(limit: int = 10):
    """List cross-model comparisons."""
    async with get_session() as session:
        result = await session.execute(
            select(ModelComparison)
            .order_by(ModelComparison.created_at.desc())
            .limit(limit)
        )
        comparisons = result.scalars().all()
        return [
            {
                "id": c.id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "summary": c.summary[:200] if c.summary else "",
            }
            for c in comparisons
        ]


@router.get("/benchmarks/{benchmark_id}")
async def get_benchmark(benchmark_id: str):
    """Get benchmark results with all metrics."""
    async with get_session() as session:
        result = await session.execute(
            select(BenchmarkRun).where(BenchmarkRun.id == benchmark_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(
                status_code=404, detail=f"Benchmark {benchmark_id} not found"
            )
        return {
            "id": run.id,
            "model_name": run.model_name,
            "model_provider": run.model_provider,
            "profile": run.profile,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "duration_seconds": run.duration_seconds,
            "metrics": json.loads(run.metrics_json) if run.metrics_json else {},
        }
