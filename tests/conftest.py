"""Shared pytest fixtures for all Sentinel test modules."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from sentinel.config.settings import SentinelSettings
from sentinel.db.connection import init_db, close_db, get_session
from sentinel.db.models import (
    Cycle, Experiment, ExperimentRun, Failure, Hypothesis, Intervention,
)


@pytest.fixture
def settings() -> SentinelSettings:
    """Default SentinelSettings for testing."""
    return SentinelSettings()


@pytest_asyncio.fixture
async def db():
    """In-memory SQLite database — creates tables and tears down after test."""
    await init_db("sqlite+aiosqlite:///:memory:")
    yield
    await close_db()


@pytest_asyncio.fixture
async def seeded_db(db):
    """DB with standard seed data: 1 cycle, 1 hypothesis, 1 experiment, 1 failure, 1 intervention."""
    cycle_id = f"cyc_{uuid.uuid4().hex[:8]}"
    hyp_id = f"hyp_{uuid.uuid4().hex[:8]}"
    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
    fail_id = f"fail_{uuid.uuid4().hex[:8]}"
    int_id = f"int_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        cycle = Cycle(
            id=cycle_id,
            target_description="Test LLM pipeline",
            mode="lab",
            started_at=now,
        )
        session.add(cycle)

    async with get_session() as session:
        hyp = Hypothesis(
            id=hyp_id,
            cycle_id=cycle_id,
            description="Model hallucinates when context is long",
            failure_class="REASONING",
            expected_severity="S2",
            status="confirmed",
        )
        session.add(hyp)

    async with get_session() as session:
        exp = Experiment(
            id=exp_id,
            hypothesis_id=hyp_id,
            input="Summarise the following 10-page document...",
            expected_correct_behavior="Accurate summary",
            expected_failure_behavior="Fabricated facts",
            num_runs=3,
            approval_status="approved",
        )
        session.add(exp)

    async with get_session() as session:
        fail = Failure(
            id=fail_id,
            experiment_id=exp_id,
            hypothesis_id=hyp_id,
            cycle_id=cycle_id,
            hypothesis_confirmed=True,
            failure_class="REASONING",
            severity="S2",
            failure_rate=0.6,
            evidence="Model fabricated statistics",
        )
        session.add(fail)

    async with get_session() as session:
        intervention = Intervention(
            id=int_id,
            failure_id=fail_id,
            cycle_id=cycle_id,
            type="prompt_mutation",
            description="Add explicit instruction to not fabricate",
            estimated_effectiveness="high",
            implementation_effort="low",
        )
        session.add(intervention)

    return {
        "cycle_id": cycle_id,
        "hypothesis_id": hyp_id,
        "experiment_id": exp_id,
        "failure_id": fail_id,
        "intervention_id": int_id,
    }


@pytest.fixture
def mock_client() -> AsyncMock:
    """AsyncMock ModelClient that returns canned JSON from generate_structured()."""
    client = AsyncMock()
    client.provider = "mock"
    # Default: return an empty list; tests override via client.generate_structured.return_value
    client.generate_structured.return_value = []
    return client
