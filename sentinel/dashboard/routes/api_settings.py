"""Settings and global stats API routes."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from sentinel.db.connection import get_session
from sentinel.db.models import AttackScan, BenchmarkRun, Cycle, Failure

router = APIRouter()


@router.get("/settings")
async def get_settings():
    """Get current Sentinel configuration."""
    from sentinel.config.settings import load_settings

    settings = load_settings()
    return {
        "mode": settings.mode.value,
        "database_url": str(settings.database.url),
        "default_model": settings.models.default,
        "research": {
            "max_hypotheses_per_run": settings.research.max_hypotheses_per_run,
            "max_experiments_per_hypothesis": settings.research.max_experiments_per_hypothesis,
        },
        "cost_limit_usd": settings.experiments.cost_limit_usd,
    }


@router.get("/settings/stats")
async def get_global_stats():
    """Global dashboard stats: total cycles, failures, benchmarks, attack scans."""
    async with get_session() as session:
        cycles_r = await session.execute(select(func.count(Cycle.id)))
        total_cycles = cycles_r.scalar() or 0

        failures_r = await session.execute(select(func.count(Failure.id)))
        total_failures = failures_r.scalar() or 0

        bench_r = await session.execute(select(func.count(BenchmarkRun.id)))
        total_benchmarks = bench_r.scalar() or 0

        scans_r = await session.execute(select(func.count(AttackScan.id)))
        total_attack_scans = scans_r.scalar() or 0

        return {
            "total_cycles": total_cycles,
            "total_failures": total_failures,
            "total_benchmarks": total_benchmarks,
            "total_attack_scans": total_attack_scans,
        }
