"""Phase 11 tests — FastAPI REST API server.

Tests cover:
- Health endpoint
- CRUD for cycles, hypotheses, failures, interventions, experiments
- Attack scan + findings endpoints
- Audit log endpoint
- Pagination
- 404 handling
- API key authentication
- Background task management
- Research + attack-scan action endpoints
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sentinel.api.app import create_app, _app_settings, _task_manager
from sentinel.api.tasks import TaskManager
from sentinel.config.settings import SentinelSettings
from sentinel.db.connection import init_db, close_db, get_session
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app():
    """Create a test FastAPI app with in-memory SQLite."""
    settings = SentinelSettings()
    settings.database.url = "sqlite+aiosqlite:///:memory:"
    test_app = create_app(settings=settings, skip_db_init=False)
    async with test_app.router.lifespan_context(test_app):
        yield test_app


@pytest_asyncio.fixture
async def client(app):
    """Async test client for the API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_app(app):
    """App with seeded test data. Returns dict of IDs."""
    cycle_id = f"cyc_{uuid.uuid4().hex[:8]}"
    hyp_id = f"hyp_{uuid.uuid4().hex[:8]}"
    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
    fail_id = f"fail_{uuid.uuid4().hex[:8]}"
    int_id = f"int_{uuid.uuid4().hex[:8]}"
    scan_id = f"scan_{uuid.uuid4().hex[:8]}"
    finding_id = f"find_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        session.add(Cycle(
            id=cycle_id, target_description="Test target", mode="lab",
            started_at=now, hypotheses_generated=1, failures_found=1,
        ))

    async with get_session() as session:
        session.add(Hypothesis(
            id=hyp_id, cycle_id=cycle_id,
            description="Model hallucinates with long context",
            failure_class="REASONING", expected_severity="S2", status="confirmed",
        ))

    async with get_session() as session:
        session.add(Experiment(
            id=exp_id, hypothesis_id=hyp_id,
            input="Summarise 10 pages...",
            expected_correct_behavior="Accurate summary",
            expected_failure_behavior="Fabricated facts",
            num_runs=3, approval_status="approved",
        ))

    async with get_session() as session:
        session.add(Failure(
            id=fail_id, experiment_id=exp_id, hypothesis_id=hyp_id,
            cycle_id=cycle_id, hypothesis_confirmed=True,
            failure_class="REASONING", severity="S2", failure_rate=0.6,
            evidence="Model fabricated statistics",
        ))

    async with get_session() as session:
        session.add(Intervention(
            id=int_id, failure_id=fail_id, cycle_id=cycle_id,
            type="prompt_mutation",
            description="Add explicit instruction to not fabricate",
            estimated_effectiveness="high", implementation_effort="low",
        ))

    async with get_session() as session:
        session.add(AuditEntry(
            event_type="cycle_started", actor="sentinel",
            entity_type="cycle", entity_id=cycle_id, details={}, mode="lab",
        ))

    async with get_session() as session:
        session.add(AttackScan(
            id=scan_id, target_description="Test target",
            started_at=now, completed_at=now,
            total_probes=5, vulnerable_probes=2, vulnerability_rate=0.4,
        ))

    async with get_session() as session:
        session.add(AttackFinding(
            id=finding_id, scan_id=scan_id, probe_id="PI-001",
            probe_name="Basic prompt injection", category="prompt_injection",
            severity="S3", vulnerable=True, vulnerability_rate=0.8,
            summary="Target followed injected instruction",
        ))

    return {
        "cycle_id": cycle_id,
        "hypothesis_id": hyp_id,
        "experiment_id": exp_id,
        "failure_id": fail_id,
        "intervention_id": int_id,
        "scan_id": scan_id,
        "finding_id": finding_id,
    }


@pytest_asyncio.fixture
async def seeded_client(app, seeded_app):
    """Client with seeded data."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, seeded_app


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert data["mode"] == "lab"

    @pytest.mark.asyncio
    async def test_health_includes_db_url(self, client):
        resp = await client.get("/api/v1/health")
        data = resp.json()
        assert "sqlite" in data["database"]


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------

class TestCycles:
    @pytest.mark.asyncio
    async def test_list_cycles_empty(self, client):
        resp = await client.get("/api/v1/cycles")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_list_cycles_with_data(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/cycles")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == ids["cycle_id"]

    @pytest.mark.asyncio
    async def test_get_cycle(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/cycles/{ids['cycle_id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == ids["cycle_id"]

    @pytest.mark.asyncio
    async def test_get_cycle_not_found(self, client):
        resp = await client.get("/api/v1/cycles/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------

class TestHypotheses:
    @pytest.mark.asyncio
    async def test_list_hypotheses(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/hypotheses")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_status(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/hypotheses?status=confirmed")
        assert resp.json()["total"] == 1

        resp = await client.get("/api/v1/hypotheses?status=rejected")
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_filter_by_cycle_id(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/hypotheses?cycle_id={ids['cycle_id']}")
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_get_hypothesis(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/hypotheses/{ids['hypothesis_id']}")
        assert resp.status_code == 200
        assert resp.json()["failure_class"] == "REASONING"

    @pytest.mark.asyncio
    async def test_get_hypothesis_not_found(self, client):
        resp = await client.get("/api/v1/hypotheses/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------

class TestFailures:
    @pytest.mark.asyncio
    async def test_list_failures(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/failures")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_class(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/failures?failure_class=REASONING")
        assert resp.json()["total"] == 1

        resp = await client.get("/api/v1/failures?failure_class=SECURITY")
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_get_failure(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/failures/{ids['failure_id']}")
        assert resp.status_code == 200
        assert resp.json()["severity"] == "S2"

    @pytest.mark.asyncio
    async def test_get_failure_not_found(self, client):
        resp = await client.get("/api/v1/failures/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Interventions
# ---------------------------------------------------------------------------

class TestInterventions:
    @pytest.mark.asyncio
    async def test_list_interventions(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/interventions")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_cycle(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/interventions?cycle_id={ids['cycle_id']}")
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_get_intervention(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/interventions/{ids['intervention_id']}")
        assert resp.status_code == 200
        assert resp.json()["type"] == "prompt_mutation"

    @pytest.mark.asyncio
    async def test_get_intervention_not_found(self, client):
        resp = await client.get("/api/v1/interventions/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

class TestExperiments:
    @pytest.mark.asyncio
    async def test_list_experiments(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/experiments")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_hypothesis(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/experiments?hypothesis_id={ids['hypothesis_id']}")
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_get_experiment(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/experiments/{ids['experiment_id']}")
        assert resp.status_code == 200
        assert resp.json()["approval_status"] == "approved"

    @pytest.mark.asyncio
    async def test_get_experiment_not_found(self, client):
        resp = await client.get("/api/v1/experiments/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Attack Scans
# ---------------------------------------------------------------------------

class TestAttackScans:
    @pytest.mark.asyncio
    async def test_list_attack_scans(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/attack-scans")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_get_attack_scan(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/attack-scans/{ids['scan_id']}")
        assert resp.status_code == 200
        assert resp.json()["total_probes"] == 5

    @pytest.mark.asyncio
    async def test_get_attack_scan_not_found(self, client):
        resp = await client.get("/api/v1/attack-scans/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_attack_findings(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get(f"/api/v1/attack-scans/{ids['scan_id']}/findings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["vulnerable"] is True


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class TestAudit:
    @pytest.mark.asyncio
    async def test_list_audit(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_filter_audit_by_event_type(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/audit?event_type=cycle_started")
        assert resp.json()["total"] == 1

        resp = await client.get("/api/v1/audit?event_type=nonexistent_event")
        assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    @pytest.mark.asyncio
    async def test_pagination_params(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/cycles?offset=0&limit=10")
        data = resp.json()
        assert data["offset"] == 0
        assert data["limit"] == 10

    @pytest.mark.asyncio
    async def test_pagination_offset_beyond(self, seeded_client):
        client, ids = seeded_client
        resp = await client.get("/api/v1/cycles?offset=100")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"] == []


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuth:
    @pytest.mark.asyncio
    async def test_no_auth_when_key_not_set(self, client):
        """When SENTINEL_API_KEY is not set, all requests should pass."""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_auth_rejects_missing_key(self, app):
        """When SENTINEL_API_KEY is set, requests without key should fail."""
        with patch.dict(os.environ, {"SENTINEL_API_KEY": "test-secret-key"}):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/health")
                assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_rejects_wrong_key(self, app):
        with patch.dict(os.environ, {"SENTINEL_API_KEY": "test-secret-key"}):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/v1/health",
                    headers={"X-API-Key": "wrong-key"},
                )
                assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_auth_accepts_correct_key(self, app):
        with patch.dict(os.environ, {"SENTINEL_API_KEY": "test-secret-key"}):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/v1/health",
                    headers={"X-API-Key": "test-secret-key"},
                )
                assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Task Manager
# ---------------------------------------------------------------------------

class TestTaskManager:
    def test_submit_and_get(self):
        mgr = TaskManager()

        async def dummy():
            return {"ok": True}

        loop = asyncio.new_event_loop()
        try:
            info = loop.run_until_complete(self._submit(mgr, dummy()))
            # Let the task complete
            loop.run_until_complete(asyncio.sleep(0.1))
            retrieved = mgr.get(info.task_id)
            assert retrieved is not None
            assert retrieved.status == "completed"
            assert retrieved.result == {"ok": True}
        finally:
            loop.close()

    def test_task_not_found(self):
        mgr = TaskManager()
        assert mgr.get("nonexistent") is None

    def test_list_tasks(self):
        mgr = TaskManager()

        async def dummy():
            return {}

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._submit(mgr, dummy()))
            loop.run_until_complete(self._submit(mgr, dummy()))
            tasks = mgr.list_tasks()
            assert len(tasks) == 2
        finally:
            loop.close()

    def test_failed_task(self):
        mgr = TaskManager()

        async def failing():
            raise ValueError("boom")

        loop = asyncio.new_event_loop()
        try:
            info = loop.run_until_complete(self._submit(mgr, failing()))
            loop.run_until_complete(asyncio.sleep(0.1))
            assert mgr.get(info.task_id).status == "failed"
            assert "ValueError" in mgr.get(info.task_id).error
        finally:
            loop.close()

    @staticmethod
    async def _submit(mgr, coro):
        return mgr.submit(coro)


# ---------------------------------------------------------------------------
# Task status endpoint
# ---------------------------------------------------------------------------

class TestTaskEndpoints:
    @pytest.mark.asyncio
    async def test_get_task_not_found(self, client):
        resp = await client.get("/api/v1/tasks/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_tasks_empty(self, client):
        resp = await client.get("/api/v1/tasks")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Action endpoints (mocked)
# ---------------------------------------------------------------------------

class TestActions:
    @pytest.mark.asyncio
    async def test_start_research_returns_task(self, client):
        """POST /research should return 202 with a task_id."""
        resp = await client.post("/api/v1/research", json={
            "target_description": "Test target",
            "approval_mode": "auto_approve",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_start_attack_scan_returns_task(self, client):
        """POST /attack-scan should return 202 with a task_id."""
        resp = await client.post("/api/v1/attack-scan", json={
            "target_description": "Test target",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_poll_task_after_submit(self, client):
        """Can poll a task by ID after submitting."""
        resp = await client.post("/api/v1/research", json={
            "target_description": "Test",
            "approval_mode": "auto_approve",
        })
        task_id = resp.json()["task_id"]

        poll = await client.get(f"/api/v1/tasks/{task_id}")
        assert poll.status_code == 200
        assert poll.json()["task_id"] == task_id
        assert poll.json()["status"] in ("running", "completed", "failed")
