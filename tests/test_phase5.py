"""Phase 5 smoke tests — Memory Graph models, in-memory queries, and DB repository.

Tests cover:
  - Enum values and ORM model construction
  - MemoryGraph in-memory query/traversal (no DB)
  - MemoryRepository CRUD against an in-memory SQLite DB
  - populate_from_cycle end-to-end
  - summarize_for_hypothesis_engine output
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sentinel.db.connection import close_db, init_db
from sentinel.memory.models import EdgeType, MemoryEdge, MemoryNode, NodeType
from sentinel.memory.graph import MemoryGraph
from sentinel.memory.repository import MemoryRepository


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture()
async def db():
    """Spin up an in-memory SQLite DB for each test, tear down after."""
    await init_db("sqlite+aiosqlite:///:memory:")
    yield
    await close_db()


def _make_node(
    id: str,
    node_type: NodeType,
    label: str = "",
    cycle_id: str = "c1",
    **props,
) -> MemoryNode:
    return MemoryNode(
        id=id,
        node_type=node_type.value,
        entity_id=id,
        label=label,
        cycle_id=cycle_id,
        properties=props,
    )


def _make_edge(
    source_id: str,
    target_id: str,
    edge_type: EdgeType,
    **props,
) -> MemoryEdge:
    return MemoryEdge(
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type.value,
        properties=props,
    )


# ── Enums ──────────────────────────────────────────────────────────────

class TestEnums:
    def test_node_type_values(self):
        assert NodeType.CYCLE.value == "cycle"
        assert NodeType.HYPOTHESIS.value == "hypothesis"
        assert NodeType.FAILURE.value == "failure"
        assert NodeType.INTERVENTION.value == "intervention"
        assert NodeType.EXPERIMENT.value == "experiment"

    def test_edge_type_values(self):
        assert EdgeType.TESTED_IN.value == "tested_in"
        assert EdgeType.CAUSED_BY.value == "caused_by"
        assert EdgeType.FIXED_BY.value == "fixed_by"
        assert EdgeType.RELATED_TO.value == "related_to"


# ── ORM Model Construction ────────────────────────────────────────────

class TestModels:
    def test_memory_node_construction(self):
        node = _make_node("n1", NodeType.HYPOTHESIS, label="test hyp")
        assert node.id == "n1"
        assert node.node_type == "hypothesis"
        assert node.label == "test hyp"

    def test_memory_edge_construction(self):
        edge = _make_edge("n1", "n2", EdgeType.TESTED_IN)
        assert edge.source_id == "n1"
        assert edge.target_id == "n2"
        assert edge.edge_type == "tested_in"
        # weight default is server-side; None before DB insert
        assert edge.weight is None or edge.weight == 1.0


# ── MemoryGraph In-Memory Queries (no DB) ─────────────────────────────

class TestMemoryGraphQueries:
    """Test MemoryGraph query methods by directly populating internal indexes."""

    def _build_graph(self) -> MemoryGraph:
        """Build a graph with a realistic mini-dataset."""
        graph = MemoryGraph.__new__(MemoryGraph)
        from collections import defaultdict

        graph._repo = None
        graph._nodes = {}
        graph._edges = []
        graph._outgoing = defaultdict(list)
        graph._incoming = defaultdict(list)
        graph._by_type = defaultdict(list)

        nodes = [
            _make_node("cyc1", NodeType.CYCLE, "Cycle 1", cycle_id="c1"),
            _make_node(
                "hyp1", NodeType.HYPOTHESIS, "Hypothesis 1", cycle_id="c1",
                status="confirmed", failure_class="REASONING",
            ),
            _make_node(
                "hyp2", NodeType.HYPOTHESIS, "Hypothesis 2", cycle_id="c1",
                status="rejected", failure_class="TOOL_USE",
            ),
            _make_node(
                "hyp3", NodeType.HYPOTHESIS, "Hypothesis 3 (pending)", cycle_id="c1",
                status="pending", failure_class="SECURITY",
            ),
            _make_node(
                "fail1", NodeType.FAILURE, "[S3] REASONING/— — rate 60%", cycle_id="c1",
                failure_class="REASONING", severity="S3",
                hypothesis_confirmed=True, failure_rate=0.6,
            ),
            _make_node(
                "fail2", NodeType.FAILURE, "[S1] TOOL_USE/— — rate 20%", cycle_id="c1",
                failure_class="TOOL_USE", severity="S1",
                hypothesis_confirmed=False,
            ),
            _make_node(
                "intv1", NodeType.INTERVENTION, "Add guardrail", cycle_id="c1",
                validation_status="fixed",
            ),
            _make_node(
                "intv2", NodeType.INTERVENTION, "Retry logic", cycle_id="c1",
                validation_status="no_effect",
            ),
            _make_node("exp1", NodeType.EXPERIMENT, "Experiment 1", cycle_id="c1"),
        ]

        edges = [
            _make_edge("hyp1", "cyc1", EdgeType.TESTED_IN),
            _make_edge("hyp2", "cyc1", EdgeType.TESTED_IN),
            _make_edge("fail1", "hyp1", EdgeType.CAUSED_BY),
            _make_edge("fail1", "exp1", EdgeType.CONFIRMED_BY),
            _make_edge("intv1", "fail1", EdgeType.PROPOSED_FOR),
            _make_edge("fail1", "intv1", EdgeType.FIXED_BY),
            _make_edge("intv2", "fail1", EdgeType.PROPOSED_FOR),
        ]

        for n in nodes:
            graph._nodes[n.id] = n
            graph._by_type[n.node_type].append(n)

        for e in edges:
            graph._edges.append(e)
            graph._outgoing[e.source_id].append(e)
            graph._incoming[e.target_id].append(e)

        return graph

    def test_node_count(self):
        g = self._build_graph()
        assert g.node_count == 9

    def test_edge_count(self):
        g = self._build_graph()
        assert g.edge_count == 7

    def test_get_node(self):
        g = self._build_graph()
        assert g.get_node("hyp1") is not None
        assert g.get_node("nonexistent") is None

    def test_get_nodes_by_type(self):
        g = self._build_graph()
        hyps = g.get_nodes_by_type(NodeType.HYPOTHESIS)
        assert len(hyps) == 3
        cycles = g.get_nodes_by_type(NodeType.CYCLE)
        assert len(cycles) == 1

    def test_get_tested_hypotheses(self):
        g = self._build_graph()
        tested = g.get_tested_hypotheses()
        # hyp1 (confirmed) + hyp2 (rejected), NOT hyp3 (pending)
        assert len(tested) == 2
        ids = {n.id for n in tested}
        assert "hyp1" in ids
        assert "hyp2" in ids
        assert "hyp3" not in ids

    def test_get_confirmed_failures(self):
        g = self._build_graph()
        confirmed = g.get_confirmed_failures()
        assert len(confirmed) == 1
        assert confirmed[0].id == "fail1"

    def test_get_failures_by_class(self):
        g = self._build_graph()
        reasoning = g.get_failures_by_class("reasoning")
        assert len(reasoning) == 1
        assert reasoning[0].id == "fail1"
        security = g.get_failures_by_class("SECURITY")
        assert len(security) == 0

    def test_get_effective_interventions(self):
        g = self._build_graph()
        effective = g.get_effective_interventions()
        assert len(effective) == 1
        assert effective[0].id == "intv1"

    def test_get_failed_interventions(self):
        g = self._build_graph()
        failed = g.get_failed_interventions()
        assert len(failed) == 1
        assert failed[0].id == "intv2"

    def test_get_outgoing(self):
        g = self._build_graph()
        out = g.get_outgoing("fail1")
        assert len(out) == 3  # CAUSED_BY, CONFIRMED_BY, FIXED_BY
        # Filter by type
        caused = g.get_outgoing("fail1", EdgeType.CAUSED_BY)
        assert len(caused) == 1
        assert caused[0].target_id == "hyp1"

    def test_get_incoming(self):
        g = self._build_graph()
        inc = g.get_incoming("fail1")
        assert len(inc) == 2  # PROPOSED_FOR from intv1 and intv2
        filtered = g.get_incoming("fail1", EdgeType.PROPOSED_FOR)
        assert len(filtered) == 2

    def test_find_related_bfs(self):
        g = self._build_graph()
        # From fail1, depth=1: hyp1, exp1, intv1, intv2 (direct neighbors)
        related = g.find_related("fail1", max_depth=1)
        ids = {n.id for n in related}
        assert "hyp1" in ids
        assert "exp1" in ids
        assert "intv1" in ids

    def test_find_related_nonexistent(self):
        g = self._build_graph()
        assert g.find_related("ghost") == []

    def test_find_related_depth_2(self):
        g = self._build_graph()
        # depth=2 should reach cyc1 (via hyp1→cyc1)
        related = g.find_related("fail1", max_depth=2)
        ids = {n.id for n in related}
        assert "cyc1" in ids

    def test_stats(self):
        g = self._build_graph()
        s = g.stats()
        assert s["total_nodes"] == 9
        assert s["total_edges"] == 7
        assert s["hypotheses"] == 3
        assert s["failures"] == 2
        assert s["interventions"] == 2
        assert s["confirmed_failures"] == 1
        assert s["effective_interventions"] == 1

    def test_cycle_summary(self):
        g = self._build_graph()
        summary = g.get_cycle_summary("c1")
        assert summary["cycle_id"] == "c1"
        assert summary["hypotheses_count"] == 3
        assert summary["failures_count"] == 2
        assert summary["confirmed_failures"] == 1
        assert summary["interventions_count"] == 2
        assert summary["effective_interventions"] == 1
        assert "S3" in summary["severity_distribution"]

    def test_summarize_for_hypothesis_engine(self):
        g = self._build_graph()
        text = g.summarize_for_hypothesis_engine()
        assert "TESTED HYPOTHESES" in text
        assert "CONFIRMED" in text
        assert "CONFIRMED FAILURES" in text
        assert "INTERVENTIONS THAT WORKED" in text
        assert "INTERVENTIONS THAT DID NOT WORK" in text
        assert "FAILURE CLASS COVERAGE" in text

    def test_summarize_empty_graph(self):
        g = MemoryGraph.__new__(MemoryGraph)
        from collections import defaultdict
        g._repo = None
        g._nodes = {}
        g._edges = []
        g._outgoing = defaultdict(list)
        g._incoming = defaultdict(list)
        g._by_type = defaultdict(list)
        text = g.summarize_for_hypothesis_engine()
        assert "first research cycle" in text


# ── Repository DB Tests ───────────────────────────────────────────────

class TestMemoryRepository:
    async def test_save_and_get_node(self, db):
        repo = MemoryRepository()
        node = _make_node("n1", NodeType.HYPOTHESIS, "test hyp")
        await repo.save_node(node)

        fetched = await repo.get_node("n1")
        assert fetched is not None
        assert fetched.label == "test hyp"
        assert fetched.node_type == "hypothesis"

    async def test_save_node_update(self, db):
        repo = MemoryRepository()
        node = _make_node("n1", NodeType.HYPOTHESIS, "original")
        await repo.save_node(node)

        updated = _make_node("n1", NodeType.HYPOTHESIS, "updated")
        await repo.save_node(updated)

        fetched = await repo.get_node("n1")
        assert fetched.label == "updated"

    async def test_get_nodes_by_type(self, db):
        repo = MemoryRepository()
        await repo.save_node(_make_node("h1", NodeType.HYPOTHESIS, "hyp1"))
        await repo.save_node(_make_node("h2", NodeType.HYPOTHESIS, "hyp2"))
        await repo.save_node(_make_node("f1", NodeType.FAILURE, "fail1"))

        hyps = await repo.get_nodes_by_type(NodeType.HYPOTHESIS)
        assert len(hyps) == 2
        fails = await repo.get_nodes_by_type(NodeType.FAILURE)
        assert len(fails) == 1

    async def test_get_nodes_by_type_with_cycle_filter(self, db):
        repo = MemoryRepository()
        await repo.save_node(_make_node("h1", NodeType.HYPOTHESIS, "hyp1", cycle_id="c1"))
        await repo.save_node(_make_node("h2", NodeType.HYPOTHESIS, "hyp2", cycle_id="c2"))

        c1_hyps = await repo.get_nodes_by_type(NodeType.HYPOTHESIS, cycle_id="c1")
        assert len(c1_hyps) == 1
        assert c1_hyps[0].id == "h1"

    async def test_save_edge_and_query(self, db):
        repo = MemoryRepository()
        await repo.save_node(_make_node("h1", NodeType.HYPOTHESIS, "hyp"))
        await repo.save_node(_make_node("c1", NodeType.CYCLE, "cycle"))
        await repo.save_edge(_make_edge("h1", "c1", EdgeType.TESTED_IN))

        from_h1 = await repo.get_edges_from("h1")
        assert len(from_h1) == 1
        assert from_h1[0].edge_type == "tested_in"

        to_c1 = await repo.get_edges_to("c1")
        assert len(to_c1) == 1

        by_type = await repo.get_edges_by_type(EdgeType.TESTED_IN)
        assert len(by_type) == 1

    async def test_load_all(self, db):
        repo = MemoryRepository()
        await repo.save_node(_make_node("n1", NodeType.HYPOTHESIS, "hyp"))
        await repo.save_node(_make_node("n2", NodeType.CYCLE, "cycle"))
        await repo.save_edge(_make_edge("n1", "n2", EdgeType.TESTED_IN))

        nodes, edges = await repo.load_all()
        assert len(nodes) == 2
        assert len(edges) == 1

    async def test_clear(self, db):
        repo = MemoryRepository()
        await repo.save_node(_make_node("n1", NodeType.HYPOTHESIS, "hyp"))
        await repo.save_node(_make_node("n2", NodeType.CYCLE, "cycle"))
        await repo.save_edge(_make_edge("n1", "n2", EdgeType.TESTED_IN))

        await repo.clear()
        nodes, edges = await repo.load_all()
        assert len(nodes) == 0
        assert len(edges) == 0

    async def test_get_all_nodes(self, db):
        repo = MemoryRepository()
        await repo.save_node(_make_node("a", NodeType.HYPOTHESIS, "a"))
        await repo.save_node(_make_node("b", NodeType.FAILURE, "b"))
        await repo.save_node(_make_node("c", NodeType.CYCLE, "c"))

        all_nodes = await repo.get_all_nodes()
        assert len(all_nodes) == 3


# ── MemoryGraph.load() Integration ────────────────────────────────────

class TestMemoryGraphLoad:
    async def test_load_from_db(self, db):
        repo = MemoryRepository()
        await repo.save_node(_make_node("h1", NodeType.HYPOTHESIS, "hyp1"))
        await repo.save_node(_make_node("c1", NodeType.CYCLE, "cycle1"))
        await repo.save_edge(_make_edge("h1", "c1", EdgeType.TESTED_IN))

        graph = MemoryGraph(repository=repo)
        await graph.load()

        assert graph.node_count == 2
        assert graph.edge_count == 1
        assert graph.get_node("h1") is not None
        assert len(graph.get_outgoing("h1", EdgeType.TESTED_IN)) == 1


# ── populate_from_cycle Integration ───────────────────────────────────

class TestPopulateFromCycle:
    async def test_populate_creates_nodes_and_edges(self, db):
        """Seed a cycle with hypotheses/experiments/failures/interventions,
        then verify populate_from_cycle creates the correct graph."""
        from sentinel.db.connection import get_session
        from sentinel.db.models import Cycle, Experiment, Failure, Hypothesis, Intervention

        # Seed research data
        async with get_session() as session:
            session.add(Cycle(
                id="cyc-1", target_description="test target", mode="lab",
                hypotheses_generated=1, hypotheses_confirmed=1, failures_found=1,
            ))
        async with get_session() as session:
            session.add(Hypothesis(
                id="hyp-1", cycle_id="cyc-1", description="System hallucinates on long context",
                failure_class="LONG_CONTEXT", expected_severity="S2", status="confirmed",
                rationale="Context window overflow",
            ))
        async with get_session() as session:
            session.add(Experiment(
                id="exp-1", hypothesis_id="hyp-1",
                input="Summarize this 100k token document",
                context_setup="Load large doc",
                expected_correct_behavior="Accurate summary",
                expected_failure_behavior="Hallucinated facts",
                num_runs=5, approval_status="approved",
            ))
        async with get_session() as session:
            session.add(Failure(
                id="fail-1", experiment_id="exp-1", hypothesis_id="hyp-1", cycle_id="cyc-1",
                failure_class="LONG_CONTEXT", severity="S2",
                failure_rate=0.6, hypothesis_confirmed=True,
                evidence="3 of 5 runs contained hallucinated facts",
            ))
        async with get_session() as session:
            session.add(Intervention(
                id="intv-1", failure_id="fail-1", type="guardrail",
                description="Add chunk-based summarization",
                estimated_effectiveness=0.8,
                validation_status="fixed",
                failure_rate_before=0.6, failure_rate_after=0.1,
            ))

        # Populate graph
        repo = MemoryRepository()
        count = await repo.populate_from_cycle("cyc-1")

        # 1 cycle + 1 hypothesis + 1 experiment + 1 failure + 1 intervention = 5
        assert count == 5

        # Verify graph structure
        nodes, edges = await repo.load_all()
        assert len(nodes) == 5

        node_types = {n.node_type for n in nodes}
        assert node_types == {"cycle", "hypothesis", "experiment", "failure", "intervention"}

        # Edges: TESTED_IN, CAUSED_BY, CONFIRMED_BY, PROPOSED_FOR, FIXED_BY = 5
        assert len(edges) == 5
        edge_types = {e.edge_type for e in edges}
        assert "tested_in" in edge_types
        assert "caused_by" in edge_types
        assert "confirmed_by" in edge_types
        assert "proposed_for" in edge_types
        assert "fixed_by" in edge_types

    async def test_populate_nonexistent_cycle(self, db):
        repo = MemoryRepository()
        count = await repo.populate_from_cycle("nonexistent")
        assert count == 0
