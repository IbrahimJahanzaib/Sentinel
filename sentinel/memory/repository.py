"""Memory graph repository — DB-backed CRUD for knowledge graph nodes and edges.

Handles persistence of the memory graph and provides methods to populate it
from completed research cycles.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select

from sentinel.db.connection import get_session
from sentinel.db.models import (
    Cycle,
    Experiment,
    Failure,
    Hypothesis,
    Intervention,
)
from sentinel.memory.models import EdgeType, MemoryEdge, MemoryNode, NodeType


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class MemoryRepository:
    """DB-backed CRUD for the knowledge graph."""

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    async def save_node(self, node: MemoryNode) -> None:
        """Insert or update a memory node."""
        async with get_session() as session:
            existing = await session.get(MemoryNode, node.id)
            if existing:
                existing.label = node.label
                existing.properties = node.properties
            else:
                session.add(node)

    async def get_node(self, node_id: str) -> Optional[MemoryNode]:
        async with get_session() as session:
            return await session.get(MemoryNode, node_id)

    async def get_nodes_by_type(
        self,
        node_type: NodeType,
        cycle_id: Optional[str] = None,
    ) -> list[MemoryNode]:
        async with get_session() as session:
            stmt = select(MemoryNode).where(MemoryNode.node_type == node_type.value)
            if cycle_id:
                stmt = stmt.where(MemoryNode.cycle_id == cycle_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_all_nodes(self) -> list[MemoryNode]:
        async with get_session() as session:
            result = await session.execute(select(MemoryNode))
            return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    async def save_edge(self, edge: MemoryEdge) -> None:
        async with get_session() as session:
            session.add(edge)

    async def get_edges_from(self, source_id: str) -> list[MemoryEdge]:
        async with get_session() as session:
            result = await session.execute(
                select(MemoryEdge).where(MemoryEdge.source_id == source_id)
            )
            return list(result.scalars().all())

    async def get_edges_to(self, target_id: str) -> list[MemoryEdge]:
        async with get_session() as session:
            result = await session.execute(
                select(MemoryEdge).where(MemoryEdge.target_id == target_id)
            )
            return list(result.scalars().all())

    async def get_edges_by_type(self, edge_type: EdgeType) -> list[MemoryEdge]:
        async with get_session() as session:
            result = await session.execute(
                select(MemoryEdge).where(MemoryEdge.edge_type == edge_type.value)
            )
            return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Bulk load
    # ------------------------------------------------------------------

    async def load_all(self) -> tuple[list[MemoryNode], list[MemoryEdge]]:
        """Load the entire graph from the database."""
        async with get_session() as session:
            nodes = list((await session.execute(select(MemoryNode))).scalars().all())
            edges = list((await session.execute(select(MemoryEdge))).scalars().all())
            return nodes, edges

    # ------------------------------------------------------------------
    # Populate from a completed cycle
    # ------------------------------------------------------------------

    async def populate_from_cycle(self, cycle_id: str) -> int:
        """Create graph nodes and edges from a completed research cycle.

        Reads the Cycle, Hypothesis, Experiment, Failure, and Intervention
        tables and creates corresponding MemoryNode/MemoryEdge records.

        Returns the number of nodes created.
        """
        node_count = 0

        async with get_session() as session:
            # ── Cycle node ──────────────────────────────────────
            cycle = await session.get(Cycle, cycle_id)
            if not cycle:
                return 0

            cycle_node_id = f"mem_cycle_{cycle_id}"
            cycle_node = MemoryNode(
                id=cycle_node_id,
                node_type=NodeType.CYCLE.value,
                entity_id=cycle_id,
                label=f"Cycle {cycle_id} — {cycle.focus or 'all'} ({cycle.mode})",
                cycle_id=cycle_id,
                properties={
                    "focus": cycle.focus,
                    "mode": cycle.mode,
                    "hypotheses_generated": cycle.hypotheses_generated,
                    "hypotheses_confirmed": cycle.hypotheses_confirmed,
                    "failures_found": cycle.failures_found,
                    "total_cost_usd": cycle.total_cost_usd,
                },
            )
            session.add(cycle_node)
            node_count += 1

            # ── Hypothesis nodes ────────────────────────────────
            hyps = (await session.execute(
                select(Hypothesis).where(Hypothesis.cycle_id == cycle_id)
            )).scalars().all()

            for hyp in hyps:
                hyp_node_id = f"mem_hyp_{hyp.id}"
                hyp_node = MemoryNode(
                    id=hyp_node_id,
                    node_type=NodeType.HYPOTHESIS.value,
                    entity_id=hyp.id,
                    label=hyp.description[:200],
                    cycle_id=cycle_id,
                    properties={
                        "failure_class": hyp.failure_class,
                        "expected_severity": hyp.expected_severity,
                        "status": hyp.status,
                        "rationale": hyp.rationale[:300] if hyp.rationale else "",
                    },
                )
                session.add(hyp_node)
                node_count += 1

                # hypothesis → cycle (TESTED_IN)
                session.add(MemoryEdge(
                    source_id=hyp_node_id,
                    target_id=cycle_node_id,
                    edge_type=EdgeType.TESTED_IN.value,
                ))

                # ── Experiment nodes for this hypothesis ────────
                exps = (await session.execute(
                    select(Experiment).where(Experiment.hypothesis_id == hyp.id)
                )).scalars().all()

                for exp in exps:
                    exp_node_id = f"mem_exp_{exp.id}"
                    exp_node = MemoryNode(
                        id=exp_node_id,
                        node_type=NodeType.EXPERIMENT.value,
                        entity_id=exp.id,
                        label=exp.input[:200],
                        cycle_id=cycle_id,
                        properties={
                            "num_runs": exp.num_runs,
                            "approval_status": exp.approval_status,
                        },
                    )
                    session.add(exp_node)
                    node_count += 1

                # ── Failure nodes for this hypothesis ───────────
                failures = (await session.execute(
                    select(Failure).where(Failure.hypothesis_id == hyp.id)
                )).scalars().all()

                for fail in failures:
                    fail_node_id = f"mem_fail_{fail.id}"
                    fail_node = MemoryNode(
                        id=fail_node_id,
                        node_type=NodeType.FAILURE.value,
                        entity_id=fail.id,
                        label=f"[{fail.severity}] {fail.failure_class}/{fail.failure_subtype or '—'} — rate {fail.failure_rate:.0%}",
                        cycle_id=cycle_id,
                        properties={
                            "failure_class": fail.failure_class,
                            "failure_subtype": fail.failure_subtype,
                            "severity": fail.severity,
                            "failure_rate": fail.failure_rate,
                            "hypothesis_confirmed": fail.hypothesis_confirmed,
                            "evidence": fail.evidence[:500] if fail.evidence else "",
                        },
                    )
                    session.add(fail_node)
                    node_count += 1

                    # failure → hypothesis (CAUSED_BY)
                    session.add(MemoryEdge(
                        source_id=fail_node_id,
                        target_id=hyp_node_id,
                        edge_type=EdgeType.CAUSED_BY.value,
                    ))

                    # failure → experiment (CONFIRMED_BY)
                    session.add(MemoryEdge(
                        source_id=fail_node_id,
                        target_id=f"mem_exp_{fail.experiment_id}",
                        edge_type=EdgeType.CONFIRMED_BY.value,
                    ))

                    # ── Intervention nodes for this failure ─────
                    interventions = (await session.execute(
                        select(Intervention).where(Intervention.failure_id == fail.id)
                    )).scalars().all()

                    for intv in interventions:
                        intv_node_id = f"mem_intv_{intv.id}"
                        intv_node = MemoryNode(
                            id=intv_node_id,
                            node_type=NodeType.INTERVENTION.value,
                            entity_id=intv.id,
                            label=intv.description[:200],
                            cycle_id=cycle_id,
                            properties={
                                "type": intv.type,
                                "estimated_effectiveness": intv.estimated_effectiveness,
                                "validation_status": intv.validation_status,
                                "failure_rate_before": intv.failure_rate_before,
                                "failure_rate_after": intv.failure_rate_after,
                            },
                        )
                        session.add(intv_node)
                        node_count += 1

                        # intervention → failure (PROPOSED_FOR)
                        session.add(MemoryEdge(
                            source_id=intv_node_id,
                            target_id=fail_node_id,
                            edge_type=EdgeType.PROPOSED_FOR.value,
                        ))

                        # If validated as fixed, add FIXED_BY edge
                        if intv.validation_status == "fixed":
                            session.add(MemoryEdge(
                                source_id=fail_node_id,
                                target_id=intv_node_id,
                                edge_type=EdgeType.FIXED_BY.value,
                            ))

        return node_count

    # ------------------------------------------------------------------
    # Cross-cycle linking
    # ------------------------------------------------------------------

    async def link_related_failures(self, max_per_node: int = 5) -> int:
        """Create RELATED_TO edges between failures sharing a failure class.

        Only links failures from different cycles. Returns the number of
        edges created.
        """
        edges_created = 0
        async with get_session() as session:
            fail_nodes = (await session.execute(
                select(MemoryNode).where(MemoryNode.node_type == NodeType.FAILURE.value)
            )).scalars().all()

            # Group by failure class
            by_class: dict[str, list[MemoryNode]] = {}
            for node in fail_nodes:
                fc = node.properties.get("failure_class", "")
                by_class.setdefault(fc, []).append(node)

            # Create cross-cycle links
            for fc, nodes in by_class.items():
                for i, a in enumerate(nodes):
                    linked = 0
                    for b in nodes[i + 1:]:
                        if a.cycle_id == b.cycle_id:
                            continue
                        if linked >= max_per_node:
                            break
                        # Check if edge already exists
                        existing = await session.execute(
                            select(MemoryEdge).where(
                                MemoryEdge.source_id == a.id,
                                MemoryEdge.target_id == b.id,
                                MemoryEdge.edge_type == EdgeType.RELATED_TO.value,
                            )
                        )
                        if existing.scalar_one_or_none():
                            continue
                        session.add(MemoryEdge(
                            source_id=a.id,
                            target_id=b.id,
                            edge_type=EdgeType.RELATED_TO.value,
                            properties={"shared_class": fc},
                        ))
                        edges_created += 1
                        linked += 1

        return edges_created

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def clear(self) -> None:
        """Delete all memory graph data. Use with caution."""
        async with get_session() as session:
            await session.execute(delete(MemoryEdge))
            await session.execute(delete(MemoryNode))
