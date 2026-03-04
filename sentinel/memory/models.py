"""Memory graph ORM tables and Pydantic models.

The memory graph stores cross-cycle knowledge as a directed graph of nodes
(hypotheses, failures, interventions, cycles) and edges (relationships).
This lets the hypothesis engine generate novel hypotheses informed by
everything Sentinel has already discovered.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel.db.connection import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    """Types of nodes in the memory graph."""
    CYCLE = "cycle"
    HYPOTHESIS = "hypothesis"
    FAILURE = "failure"
    INTERVENTION = "intervention"
    EXPERIMENT = "experiment"


class EdgeType(str, Enum):
    """Types of edges connecting memory graph nodes."""
    TESTED_IN = "tested_in"             # hypothesis → cycle
    CONFIRMED_BY = "confirmed_by"       # failure → experiment
    PROPOSED_FOR = "proposed_for"       # intervention → failure
    VALIDATED_BY = "validated_by"       # intervention → experiment
    RELATED_TO = "related_to"           # any → any (same failure class, similar description)
    INFORMS = "informs"                 # finding from cycle N → hypothesis in cycle N+1
    FIXED_BY = "fixed_by"              # failure → intervention (when validated as fixed)
    CAUSED_BY = "caused_by"            # failure → hypothesis


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class MemoryNode(Base):
    """A node in the persistent knowledge graph."""
    __tablename__ = "memory_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(Text, default="")
    cycle_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    outgoing_edges: Mapped[list["MemoryEdge"]] = relationship(
        "MemoryEdge",
        foreign_keys="MemoryEdge.source_id",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list["MemoryEdge"]] = relationship(
        "MemoryEdge",
        foreign_keys="MemoryEdge.target_id",
        back_populates="target",
        cascade="all, delete-orphan",
    )


class MemoryEdge(Base):
    """A directed edge in the persistent knowledge graph."""
    __tablename__ = "memory_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_nodes.id", ondelete="CASCADE"), nullable=False
    )
    edge_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    source: Mapped["MemoryNode"] = relationship(
        "MemoryNode", foreign_keys=[source_id], back_populates="outgoing_edges"
    )
    target: Mapped["MemoryNode"] = relationship(
        "MemoryNode", foreign_keys=[target_id], back_populates="incoming_edges"
    )
