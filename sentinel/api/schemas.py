"""Pydantic response/request schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

class PaginationParams(BaseModel):
    offset: int = 0
    limit: int = 50


class PaginatedResponse(BaseModel):
    total: int
    offset: int
    limit: int


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    mode: str
    database: str


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------

class CycleOut(BaseModel):
    id: str
    target_description: str
    focus: Optional[str]
    mode: str
    hypotheses_generated: int
    hypotheses_confirmed: int
    experiments_run: int
    failures_found: int
    started_at: datetime
    ended_at: Optional[datetime]
    total_cost_usd: float
    total_tokens: int
    notes: str

    model_config = {"from_attributes": True}


class CycleListResponse(PaginatedResponse):
    items: list[CycleOut]


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------

class HypothesisOut(BaseModel):
    id: str
    cycle_id: Optional[str]
    description: str
    failure_class: str
    expected_severity: str
    rationale: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HypothesisListResponse(PaginatedResponse):
    items: list[HypothesisOut]


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------

class FailureOut(BaseModel):
    id: str
    experiment_id: str
    hypothesis_id: str
    cycle_id: Optional[str]
    hypothesis_confirmed: bool
    failure_class: str
    failure_subtype: str
    severity: str
    failure_rate: float
    evidence: str
    sample_failure_output: str
    sample_correct_output: str
    created_at: datetime

    model_config = {"from_attributes": True}


class FailureListResponse(PaginatedResponse):
    items: list[FailureOut]


# ---------------------------------------------------------------------------
# Interventions
# ---------------------------------------------------------------------------

class InterventionOut(BaseModel):
    id: str
    failure_id: str
    cycle_id: Optional[str]
    type: str
    description: str
    estimated_effectiveness: str
    implementation_effort: str
    validation_status: str
    validation_notes: str
    failure_rate_before: Optional[float]
    failure_rate_after: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class InterventionListResponse(PaginatedResponse):
    items: list[InterventionOut]


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

class ExperimentOut(BaseModel):
    id: str
    hypothesis_id: str
    input: str
    context_setup: str
    expected_correct_behavior: str
    expected_failure_behavior: str
    num_runs: int
    approval_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ExperimentListResponse(PaginatedResponse):
    items: list[ExperimentOut]


# ---------------------------------------------------------------------------
# Attack Scans
# ---------------------------------------------------------------------------

class AttackScanOut(BaseModel):
    id: str
    target_description: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_probes: int
    vulnerable_probes: int
    vulnerability_rate: float

    model_config = {"from_attributes": True}


class AttackScanListResponse(PaginatedResponse):
    items: list[AttackScanOut]


class AttackFindingOut(BaseModel):
    id: str
    scan_id: str
    probe_id: str
    probe_name: str
    category: str
    severity: str
    vulnerable: bool
    vulnerability_rate: float
    summary: str

    model_config = {"from_attributes": True}


class AttackFindingListResponse(PaginatedResponse):
    items: list[AttackFindingOut]


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class AuditEntryOut(BaseModel):
    id: int
    timestamp: datetime
    event_type: str
    actor: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    details: dict
    mode: str

    model_config = {"from_attributes": True}


class AuditListResponse(PaginatedResponse):
    items: list[AuditEntryOut]


# ---------------------------------------------------------------------------
# Action requests
# ---------------------------------------------------------------------------

class ResearchRequest(BaseModel):
    focus: Optional[str] = None
    max_hypotheses: Optional[int] = None
    max_experiments: Optional[int] = None
    target_description: str = "A general-purpose LLM assistant"
    approval_mode: str = "auto_approve"


class AttackScanRequest(BaseModel):
    target_description: str = "A general-purpose LLM assistant"
    categories: Optional[list[str]] = None
    min_severity: Optional[str] = None
    probe_ids: Optional[list[str]] = None
    tags: Optional[list[str]] = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # pending | running | completed | failed
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
