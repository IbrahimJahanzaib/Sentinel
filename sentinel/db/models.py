"""SQLAlchemy ORM models for all Sentinel data."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .connection import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Cycle — one research run
# ---------------------------------------------------------------------------

class Cycle(Base):
    __tablename__ = "cycles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    target_description: Mapped[str] = mapped_column(Text, default="")
    focus: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(20), default="lab")

    hypotheses_generated: Mapped[int] = mapped_column(Integer, default=0)
    hypotheses_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    experiments_run: Mapped[int] = mapped_column(Integer, default=0)
    failures_found: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")

    # Relationships
    hypotheses: Mapped[list["Hypothesis"]] = relationship(
        "Hypothesis", back_populates="cycle", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------

class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    cycle_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("cycles.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    failure_class: Mapped[str] = mapped_column(String(30), nullable=False)
    expected_severity: Mapped[str] = mapped_column(String(5), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="untested")
    # untested | confirmed | rejected | skipped

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    cycle: Mapped[Optional["Cycle"]] = relationship("Cycle", back_populates="hypotheses")
    experiments: Mapped[list["Experiment"]] = relationship(
        "Experiment", back_populates="hypothesis", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------

class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    hypothesis_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=False
    )
    input: Mapped[str] = mapped_column(Text, nullable=False)
    context_setup: Mapped[str] = mapped_column(Text, default="")
    expected_correct_behavior: Mapped[str] = mapped_column(Text, default="")
    expected_failure_behavior: Mapped[str] = mapped_column(Text, default="")
    num_runs: Mapped[int] = mapped_column(Integer, default=5)

    # Approval metadata
    approval_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | approved | rejected | auto_approved | blocked

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    hypothesis: Mapped["Hypothesis"] = relationship("Hypothesis", back_populates="experiments")
    runs: Mapped[list["ExperimentRun"]] = relationship(
        "ExperimentRun", back_populates="experiment", cascade="all, delete-orphan"
    )
    failures: Mapped[list["Failure"]] = relationship(
        "Failure", back_populates="experiment", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# ExperimentRun — one execution of an experiment
# ---------------------------------------------------------------------------

class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[str] = mapped_column(Text, default="")
    retrieved_chunks: Mapped[list] = mapped_column(JSON, default=list)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    experiment: Mapped["Experiment"] = relationship("Experiment", back_populates="runs")


# ---------------------------------------------------------------------------
# Failure — classified failure from experiment results
# ---------------------------------------------------------------------------

class Failure(Base):
    __tablename__ = "failures"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    experiment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    hypothesis_id: Mapped[str] = mapped_column(String(32), nullable=False)
    cycle_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    hypothesis_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_class: Mapped[str] = mapped_column(String(30), nullable=False)
    failure_subtype: Mapped[str] = mapped_column(String(50), default="")
    severity: Mapped[str] = mapped_column(String(5), nullable=False)
    failure_rate: Mapped[float] = mapped_column(Float, default=0.0)

    evidence: Mapped[str] = mapped_column(Text, default="")
    sample_failure_output: Mapped[str] = mapped_column(Text, default="")
    sample_correct_output: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    experiment: Mapped["Experiment"] = relationship("Experiment", back_populates="failures")
    interventions: Mapped[list["Intervention"]] = relationship(
        "Intervention", back_populates="failure", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Intervention — proposed fix for a failure
# ---------------------------------------------------------------------------

class Intervention(Base):
    __tablename__ = "interventions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    failure_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("failures.id", ondelete="CASCADE"), nullable=False
    )
    cycle_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # prompt_mutation | guardrail | tool_policy_change | config_change | architectural_recommendation
    description: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_effectiveness: Mapped[str] = mapped_column(String(10), default="medium")
    implementation_effort: Mapped[str] = mapped_column(String(10), default="medium")

    # Validation result (set after simulation engine runs)
    validation_status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending | fixed | partially_fixed | no_effect | regression
    validation_notes: Mapped[str] = mapped_column(Text, default="")
    failure_rate_before: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    failure_rate_after: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    failure: Mapped["Failure"] = relationship("Failure", back_populates="interventions")


# ---------------------------------------------------------------------------
# AuditEntry — immutable audit trail for all actions
# ---------------------------------------------------------------------------

class AuditEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str] = mapped_column(String(50), default="sentinel")
    entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(20), default="lab")


# ---------------------------------------------------------------------------
# AttackScan — one attack probe scan
# ---------------------------------------------------------------------------

class AttackScan(Base):
    __tablename__ = "attack_scans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    target_description: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_probes: Mapped[int] = mapped_column(Integer, default=0)
    vulnerable_probes: Mapped[int] = mapped_column(Integer, default=0)
    vulnerability_rate: Mapped[float] = mapped_column(Float, default=0.0)
    results_json: Mapped[str] = mapped_column(Text, default="{}")

    # Relationships
    findings: Mapped[list["AttackFinding"]] = relationship(
        "AttackFinding", back_populates="scan", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# AttackFinding — one finding from an attack scan
# ---------------------------------------------------------------------------

class AttackFinding(Base):
    __tablename__ = "attack_findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    scan_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("attack_scans.id", ondelete="CASCADE"), nullable=False
    )
    probe_id: Mapped[str] = mapped_column(String(20), nullable=False)
    probe_name: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(5), nullable=False)
    vulnerable: Mapped[bool] = mapped_column(Boolean, default=False)
    vulnerability_rate: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")

    # Relationships
    scan: Mapped["AttackScan"] = relationship("AttackScan", back_populates="findings")


def _register_models() -> None:
    """Imported by connection.py to ensure all models are registered with Base.metadata."""
    # All models are defined in this module, so importing this module is sufficient.
    pass
