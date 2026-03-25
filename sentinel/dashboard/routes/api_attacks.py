"""Attack scans API routes."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from sentinel.db.connection import get_session
from sentinel.db.models import AttackScan

router = APIRouter()


@router.get("/attacks/scans")
async def list_attack_scans(limit: int = 20):
    """List all attack scan results."""
    async with get_session() as session:
        result = await session.execute(
            select(AttackScan)
            .order_by(AttackScan.started_at.desc())
            .limit(limit)
        )
        scans = result.scalars().all()
        return [
            {
                "id": s.id,
                "target_description": s.target_description,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "total_probes": s.total_probes,
                "vulnerable_probes": s.vulnerable_probes,
                "vulnerability_rate": s.vulnerability_rate,
            }
            for s in scans
        ]


@router.get("/attacks/scans/{scan_id}")
async def get_attack_scan(scan_id: str):
    """Get detailed attack scan results."""
    async with get_session() as session:
        result = await session.execute(
            select(AttackScan).where(AttackScan.id == scan_id)
        )
        scan = result.scalar_one_or_none()
        if not scan:
            raise HTTPException(
                status_code=404, detail=f"Scan {scan_id} not found"
            )
        return {
            "id": scan.id,
            "target_description": scan.target_description,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "total_probes": scan.total_probes,
            "vulnerable_probes": scan.vulnerable_probes,
            "vulnerability_rate": scan.vulnerability_rate,
            "results": json.loads(scan.results_json) if scan.results_json else {},
        }


@router.get("/attacks/probes")
async def list_probes(category: Optional[str] = None):
    """List available attack probes."""
    from sentinel.attacks.loader import ProbeLoader

    loader = ProbeLoader()
    if category:
        probes = loader.load_category(category)
    else:
        probes = loader.load_all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "severity": p.severity,
            "description": p.description[:200],
            "payload_count": len(p.payloads),
            "tags": p.tags,
        }
        for p in probes
    ]
