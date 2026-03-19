"""API route definitions — CRUD endpoints + async action triggers."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from sentinel.db.connection import get_session
from sentinel.db.models import (
    AttackFinding,
    AttackScan,
    AuditEntry,
    Cycle,
    Experiment,
    Failure,
    Hypothesis,
    Intervention,
)
from sentinel.taxonomy.failure_types import Severity

from .auth import verify_api_key
from .schemas import (
    AttackFindingListResponse,
    AttackFindingOut,
    AttackScanListResponse,
    AttackScanOut,
    AttackScanRequest,
    AuditListResponse,
    AuditEntryOut,
    CycleListResponse,
    CycleOut,
    ExperimentListResponse,
    ExperimentOut,
    FailureListResponse,
    FailureOut,
    HealthResponse,
    HypothesisListResponse,
    HypothesisOut,
    InterventionListResponse,
    InterventionOut,
    ResearchRequest,
    TaskStatusResponse,
)

router = APIRouter(dependencies=[Depends(verify_api_key)])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Health check — returns server status, version, and mode."""
    from sentinel import __version__
    from sentinel.api.app import _app_settings

    settings = _app_settings()
    return HealthResponse(
        status="ok",
        version=__version__,
        mode=settings.mode.value,
        database=settings.database.url,
    )


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------

@router.get("/cycles", response_model=CycleListResponse, tags=["cycles"])
async def list_cycles(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> CycleListResponse:
    async with get_session() as session:
        total = (await session.execute(select(func.count(Cycle.id)))).scalar_one()
        rows = (
            await session.execute(
                select(Cycle)
                .order_by(Cycle.started_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
    return CycleListResponse(
        total=total, offset=offset, limit=limit,
        items=[CycleOut.model_validate(r) for r in rows],
    )


@router.get("/cycles/{cycle_id}", response_model=CycleOut, tags=["cycles"])
async def get_cycle(cycle_id: str) -> CycleOut:
    async with get_session() as session:
        row = (await session.execute(select(Cycle).where(Cycle.id == cycle_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return CycleOut.model_validate(row)


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------

@router.get("/hypotheses", response_model=HypothesisListResponse, tags=["hypotheses"])
async def list_hypotheses(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    cycle_id: Optional[str] = None,
) -> HypothesisListResponse:
    stmt = select(Hypothesis)
    count_stmt = select(func.count(Hypothesis.id))

    if status_filter:
        stmt = stmt.where(Hypothesis.status == status_filter)
        count_stmt = count_stmt.where(Hypothesis.status == status_filter)
    if cycle_id:
        stmt = stmt.where(Hypothesis.cycle_id == cycle_id)
        count_stmt = count_stmt.where(Hypothesis.cycle_id == cycle_id)

    async with get_session() as session:
        total = (await session.execute(count_stmt)).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(Hypothesis.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()

    return HypothesisListResponse(
        total=total, offset=offset, limit=limit,
        items=[HypothesisOut.model_validate(r) for r in rows],
    )


@router.get("/hypotheses/{hypothesis_id}", response_model=HypothesisOut, tags=["hypotheses"])
async def get_hypothesis(hypothesis_id: str) -> HypothesisOut:
    async with get_session() as session:
        row = (
            await session.execute(select(Hypothesis).where(Hypothesis.id == hypothesis_id))
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Hypothesis not found")
    return HypothesisOut.model_validate(row)


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------

@router.get("/failures", response_model=FailureListResponse, tags=["failures"])
async def list_failures(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    min_severity: Optional[str] = None,
    failure_class: Optional[str] = None,
    cycle_id: Optional[str] = None,
) -> FailureListResponse:
    stmt = select(Failure)
    count_stmt = select(func.count(Failure.id))

    if failure_class:
        stmt = stmt.where(Failure.failure_class == failure_class)
        count_stmt = count_stmt.where(Failure.failure_class == failure_class)
    if cycle_id:
        stmt = stmt.where(Failure.cycle_id == cycle_id)
        count_stmt = count_stmt.where(Failure.cycle_id == cycle_id)

    async with get_session() as session:
        total = (await session.execute(count_stmt)).scalar_one()
        rows = list(
            (await session.execute(
                stmt.order_by(Failure.created_at.desc()).offset(offset).limit(limit)
            )).scalars().all()
        )

    # Post-filter by severity (severity ordering is enum-based, not alphabetical)
    if min_severity:
        threshold = Severity(min_severity.rstrip("+"))
        rows = [f for f in rows if Severity(f.severity) >= threshold]
        total = len(rows)

    return FailureListResponse(
        total=total, offset=offset, limit=limit,
        items=[FailureOut.model_validate(r) for r in rows],
    )


@router.get("/failures/{failure_id}", response_model=FailureOut, tags=["failures"])
async def get_failure(failure_id: str) -> FailureOut:
    async with get_session() as session:
        row = (
            await session.execute(select(Failure).where(Failure.id == failure_id))
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Failure not found")
    return FailureOut.model_validate(row)


# ---------------------------------------------------------------------------
# Interventions
# ---------------------------------------------------------------------------

@router.get("/interventions", response_model=InterventionListResponse, tags=["interventions"])
async def list_interventions(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    cycle_id: Optional[str] = None,
) -> InterventionListResponse:
    stmt = select(Intervention)
    count_stmt = select(func.count(Intervention.id))

    if cycle_id:
        stmt = stmt.where(Intervention.cycle_id == cycle_id)
        count_stmt = count_stmt.where(Intervention.cycle_id == cycle_id)

    async with get_session() as session:
        total = (await session.execute(count_stmt)).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(Intervention.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()

    return InterventionListResponse(
        total=total, offset=offset, limit=limit,
        items=[InterventionOut.model_validate(r) for r in rows],
    )


@router.get("/interventions/{intervention_id}", response_model=InterventionOut, tags=["interventions"])
async def get_intervention(intervention_id: str) -> InterventionOut:
    async with get_session() as session:
        row = (
            await session.execute(select(Intervention).where(Intervention.id == intervention_id))
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Intervention not found")
    return InterventionOut.model_validate(row)


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

@router.get("/experiments", response_model=ExperimentListResponse, tags=["experiments"])
async def list_experiments(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    hypothesis_id: Optional[str] = None,
) -> ExperimentListResponse:
    stmt = select(Experiment)
    count_stmt = select(func.count(Experiment.id))

    if hypothesis_id:
        stmt = stmt.where(Experiment.hypothesis_id == hypothesis_id)
        count_stmt = count_stmt.where(Experiment.hypothesis_id == hypothesis_id)

    async with get_session() as session:
        total = (await session.execute(count_stmt)).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(Experiment.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()

    return ExperimentListResponse(
        total=total, offset=offset, limit=limit,
        items=[ExperimentOut.model_validate(r) for r in rows],
    )


@router.get("/experiments/{experiment_id}", response_model=ExperimentOut, tags=["experiments"])
async def get_experiment(experiment_id: str) -> ExperimentOut:
    async with get_session() as session:
        row = (
            await session.execute(select(Experiment).where(Experiment.id == experiment_id))
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return ExperimentOut.model_validate(row)


# ---------------------------------------------------------------------------
# Attack Scans
# ---------------------------------------------------------------------------

@router.get("/attack-scans", response_model=AttackScanListResponse, tags=["attacks"])
async def list_attack_scans(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> AttackScanListResponse:
    async with get_session() as session:
        total = (await session.execute(select(func.count(AttackScan.id)))).scalar_one()
        rows = (
            await session.execute(
                select(AttackScan)
                .order_by(AttackScan.started_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()

    return AttackScanListResponse(
        total=total, offset=offset, limit=limit,
        items=[AttackScanOut.model_validate(r) for r in rows],
    )


@router.get("/attack-scans/{scan_id}", response_model=AttackScanOut, tags=["attacks"])
async def get_attack_scan(scan_id: str) -> AttackScanOut:
    async with get_session() as session:
        row = (
            await session.execute(select(AttackScan).where(AttackScan.id == scan_id))
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Attack scan not found")
    return AttackScanOut.model_validate(row)


@router.get("/attack-scans/{scan_id}/findings", response_model=AttackFindingListResponse, tags=["attacks"])
async def list_attack_findings(
    scan_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> AttackFindingListResponse:
    async with get_session() as session:
        total = (
            await session.execute(
                select(func.count(AttackFinding.id)).where(AttackFinding.scan_id == scan_id)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(AttackFinding)
                .where(AttackFinding.scan_id == scan_id)
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()

    return AttackFindingListResponse(
        total=total, offset=offset, limit=limit,
        items=[AttackFindingOut.model_validate(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/audit", response_model=AuditListResponse, tags=["audit"])
async def list_audit_entries(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = None,
) -> AuditListResponse:
    stmt = select(AuditEntry)
    count_stmt = select(func.count(AuditEntry.id))

    if event_type:
        stmt = stmt.where(AuditEntry.event_type == event_type)
        count_stmt = count_stmt.where(AuditEntry.event_type == event_type)

    async with get_session() as session:
        total = (await session.execute(count_stmt)).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(AuditEntry.timestamp.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()

    return AuditListResponse(
        total=total, offset=offset, limit=limit,
        items=[AuditEntryOut.model_validate(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# Action endpoints (async tasks)
# ---------------------------------------------------------------------------

@router.post("/research", response_model=TaskStatusResponse, status_code=202, tags=["actions"])
async def start_research(req: ResearchRequest) -> TaskStatusResponse:
    """Kick off a research cycle in the background. Returns a task ID to poll."""
    from sentinel.api.app import _app_settings, _task_manager
    from sentinel.agents.demo_target import DemoTarget
    from sentinel.core.cost_tracker import CostTracker
    from sentinel.integrations.model_client import build_default_client

    settings = _app_settings()
    tracker = CostTracker(budget_usd=settings.experiments.cost_limit_usd)
    client = build_default_client(settings, tracker)
    demo = DemoTarget(description=req.target_description, client=client)

    # Build a Sentinel instance for the cycle
    from sentinel import Sentinel

    sentinel_obj = Sentinel(settings=settings)
    sentinel_obj.settings.approval.mode = req.approval_mode

    async def _run() -> dict:
        result = await sentinel_obj.research_cycle(
            target=demo,
            focus=req.focus,
            max_hypotheses=req.max_hypotheses,
            max_experiments=req.max_experiments,
        )
        return {
            "cycle_id": result.cycle_id,
            "hypotheses": len(result.hypotheses),
            "failures": len(result.failures),
            "confirmed_failures": len(result.confirmed_failures),
            "interventions": len(result.interventions),
            "cost_usd": result.cost_summary.get("total_cost_usd", 0),
        }

    mgr = _task_manager()
    info = mgr.submit(_run())
    return TaskStatusResponse(
        task_id=info.task_id,
        status=info.status,
        started_at=info.started_at,
    )


@router.post("/attack-scan", response_model=TaskStatusResponse, status_code=202, tags=["actions"])
async def start_attack_scan(req: AttackScanRequest) -> TaskStatusResponse:
    """Kick off an attack scan in the background. Returns a task ID to poll."""
    import json as json_mod

    from sentinel.api.app import _app_settings, _task_manager
    from sentinel.agents.demo_target import DemoTarget
    from sentinel.attacks import AttackRunner, VulnerabilityClassifier
    from sentinel.core.cost_tracker import CostTracker
    from sentinel.db.models import AttackScan as AttackScanModel
    from sentinel.db.models import AttackFinding as AttackFindingModel
    from sentinel.integrations.model_client import build_default_client

    settings = _app_settings()
    tracker = CostTracker(budget_usd=settings.experiments.cost_limit_usd)
    client = build_default_client(settings, tracker)
    demo = DemoTarget(description=req.target_description, client=client)
    classifier = VulnerabilityClassifier(model_client=client)
    runner = AttackRunner(classifier=classifier, cost_tracker=tracker)

    async def _run() -> dict:
        result = await runner.scan(
            target=demo,
            categories=req.categories,
            min_severity=req.min_severity,
            probe_ids=req.probe_ids,
            tags=req.tags,
        )

        # Persist to DB
        async with get_session() as session:
            scan_row = AttackScanModel(
                id=result.scan_id,
                target_description=result.target_description,
                started_at=result.started_at,
                completed_at=result.completed_at,
                total_probes=result.total_probes,
                vulnerable_probes=result.vulnerable_probes,
                vulnerability_rate=result.vulnerability_rate,
                results_json=json_mod.dumps(result.model_dump(mode="json")),
            )
            session.add(scan_row)
            for pr in result.probe_results:
                finding = AttackFindingModel(
                    scan_id=result.scan_id,
                    probe_id=pr.probe.id,
                    probe_name=pr.probe.name,
                    category=pr.probe.category,
                    severity=pr.probe.severity,
                    vulnerable=pr.vulnerable,
                    vulnerability_rate=pr.vulnerability_rate,
                    summary=pr.summary,
                )
                session.add(finding)
            await session.commit()

        return {
            "scan_id": result.scan_id,
            "total_probes": result.total_probes,
            "vulnerable_probes": result.vulnerable_probes,
            "vulnerability_rate": result.vulnerability_rate,
            "duration_seconds": result.duration_seconds,
        }

    mgr = _task_manager()
    info = mgr.submit(_run())
    return TaskStatusResponse(
        task_id=info.task_id,
        status=info.status,
        started_at=info.started_at,
    )


# ---------------------------------------------------------------------------
# Task status polling
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}", response_model=TaskStatusResponse, tags=["tasks"])
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """Poll a background task's status."""
    from sentinel.api.app import _task_manager

    mgr = _task_manager()
    info = mgr.get(task_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusResponse(**info.to_dict())


@router.get("/tasks", tags=["tasks"])
async def list_tasks(limit: int = Query(50, ge=1, le=200)) -> list[TaskStatusResponse]:
    """List recent background tasks."""
    from sentinel.api.app import _task_manager

    mgr = _task_manager()
    return [TaskStatusResponse(**t.to_dict()) for t in mgr.list_tasks(limit=limit)]
