"""Memory Graph — in-memory knowledge graph for cross-cycle learning.

Provides query and traversal operations over the persistent knowledge graph.
The hypothesis engine uses this to avoid repeating past work and to generate
hypotheses informed by what Sentinel has already discovered.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

from sentinel.memory.models import EdgeType, MemoryEdge, MemoryNode, NodeType
from sentinel.memory.repository import MemoryRepository


class MemoryGraph:
    """In-memory query interface over the persistent knowledge graph.

    Loads nodes and edges from the database via ``MemoryRepository``,
    indexes them for fast lookup, and provides the high-level queries
    that the research agents need.

    Parameters
    ----------
    repository:
        The DB-backed repository. If omitted, a default is created.
    """

    def __init__(self, repository: Optional[MemoryRepository] = None) -> None:
        self._repo = repository or MemoryRepository()

        # In-memory indexes (populated by load())
        self._nodes: dict[str, MemoryNode] = {}
        self._edges: list[MemoryEdge] = []
        self._outgoing: dict[str, list[MemoryEdge]] = defaultdict(list)
        self._incoming: dict[str, list[MemoryEdge]] = defaultdict(list)
        self._by_type: dict[str, list[MemoryNode]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Load / refresh
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Load the full graph from the database into memory."""
        nodes, edges = await self._repo.load_all()
        self._nodes.clear()
        self._edges.clear()
        self._outgoing.clear()
        self._incoming.clear()
        self._by_type.clear()

        for node in nodes:
            self._nodes[node.id] = node
            self._by_type[node.node_type].append(node)

        for edge in edges:
            self._edges.append(edge)
            self._outgoing[edge.source_id].append(edge)
            self._incoming[edge.target_id].append(edge)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    # ------------------------------------------------------------------
    # Core queries
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[MemoryNode]:
        return self._nodes.get(node_id)

    def get_nodes_by_type(self, node_type: NodeType) -> list[MemoryNode]:
        return list(self._by_type.get(node_type.value, []))

    def get_outgoing(self, node_id: str, edge_type: Optional[EdgeType] = None) -> list[MemoryEdge]:
        edges = self._outgoing.get(node_id, [])
        if edge_type:
            return [e for e in edges if e.edge_type == edge_type.value]
        return list(edges)

    def get_incoming(self, node_id: str, edge_type: Optional[EdgeType] = None) -> list[MemoryEdge]:
        edges = self._incoming.get(node_id, [])
        if edge_type:
            return [e for e in edges if e.edge_type == edge_type.value]
        return list(edges)

    # ------------------------------------------------------------------
    # High-level queries the hypothesis engine needs
    # ------------------------------------------------------------------

    def get_tested_hypotheses(self) -> list[MemoryNode]:
        """What hypotheses have we already tested?"""
        return [
            n for n in self.get_nodes_by_type(NodeType.HYPOTHESIS)
            if n.properties.get("status") in ("confirmed", "rejected")
        ]

    def get_confirmed_failures(self) -> list[MemoryNode]:
        """All failures that confirmed their hypothesis."""
        return [
            n for n in self.get_nodes_by_type(NodeType.FAILURE)
            if n.properties.get("hypothesis_confirmed")
        ]

    def get_failures_by_class(self, failure_class: str) -> list[MemoryNode]:
        """Failures in a specific failure class."""
        return [
            n for n in self.get_nodes_by_type(NodeType.FAILURE)
            if n.properties.get("failure_class") == failure_class.upper()
        ]

    def get_effective_interventions(self) -> list[MemoryNode]:
        """Interventions that were validated as 'fixed' or 'partially_fixed'."""
        return [
            n for n in self.get_nodes_by_type(NodeType.INTERVENTION)
            if n.properties.get("validation_status") in ("fixed", "partially_fixed")
        ]

    def get_failed_interventions(self) -> list[MemoryNode]:
        """Interventions that had 'no_effect' or 'regression'."""
        return [
            n for n in self.get_nodes_by_type(NodeType.INTERVENTION)
            if n.properties.get("validation_status") in ("no_effect", "regression")
        ]

    def get_knowledge_at(self, timestamp: datetime) -> list[MemoryNode]:
        """What did we know at a specific point in time?"""
        return [
            n for n in self._nodes.values()
            if n.created_at <= timestamp
        ]

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def find_related(self, node_id: str, max_depth: int = 2) -> list[MemoryNode]:
        """BFS traversal to find nodes related to a starting node."""
        if node_id not in self._nodes:
            return []

        visited: set[str] = {node_id}
        frontier: list[str] = [node_id]
        results: list[MemoryNode] = []

        for _ in range(max_depth):
            next_frontier: list[str] = []
            for nid in frontier:
                for edge in self._outgoing.get(nid, []) + self._incoming.get(nid, []):
                    neighbor = edge.target_id if edge.source_id == nid else edge.source_id
                    if neighbor not in visited and neighbor in self._nodes:
                        visited.add(neighbor)
                        next_frontier.append(neighbor)
                        results.append(self._nodes[neighbor])
            frontier = next_frontier

        return results

    def get_cycle_summary(self, cycle_id: str) -> dict:
        """Get a summary of what was found in a specific cycle."""
        cycle_nodes = [n for n in self._nodes.values() if n.cycle_id == cycle_id]

        hypotheses = [n for n in cycle_nodes if n.node_type == NodeType.HYPOTHESIS.value]
        failures = [n for n in cycle_nodes if n.node_type == NodeType.FAILURE.value]
        interventions = [n for n in cycle_nodes if n.node_type == NodeType.INTERVENTION.value]

        return {
            "cycle_id": cycle_id,
            "hypotheses_count": len(hypotheses),
            "confirmed_count": sum(
                1 for n in hypotheses if n.properties.get("status") == "confirmed"
            ),
            "failures_count": len(failures),
            "confirmed_failures": sum(
                1 for n in failures if n.properties.get("hypothesis_confirmed")
            ),
            "interventions_count": len(interventions),
            "effective_interventions": sum(
                1 for n in interventions
                if n.properties.get("validation_status") in ("fixed", "partially_fixed")
            ),
            "severity_distribution": self._severity_distribution(failures),
            "failure_classes": list({
                n.properties.get("failure_class", "")
                for n in failures if n.properties.get("hypothesis_confirmed")
            }),
        }

    # ------------------------------------------------------------------
    # Formatted output for agents
    # ------------------------------------------------------------------

    def summarize_for_hypothesis_engine(self, max_items: int = 50) -> str:
        """Generate a formatted summary for the hypothesis engine's LLM prompt.

        This replaces the simple DB query in hypothesis_engine._load_previous_findings()
        with a richer, graph-aware summary that includes failures, interventions,
        and cross-cycle patterns.
        """
        lines: list[str] = []

        # 1. Tested hypotheses
        tested = self.get_tested_hypotheses()
        if tested:
            lines.append("=== TESTED HYPOTHESES ===")
            for h in tested[:max_items]:
                status = h.properties.get("status", "unknown").upper()
                fc = h.properties.get("failure_class", "?")
                lines.append(f"  [{status}] ({fc}) {h.label[:100]}")
            if len(tested) > max_items:
                lines.append(f"  ... and {len(tested) - max_items} more")
        else:
            lines.append("=== No previous hypotheses tested ===")

        # 2. Confirmed failures
        confirmed = self.get_confirmed_failures()
        if confirmed:
            lines.append("\n=== CONFIRMED FAILURES ===")
            for f in confirmed[:max_items]:
                lines.append(f"  {f.label[:120]}")
            if len(confirmed) > max_items:
                lines.append(f"  ... and {len(confirmed) - max_items} more")

        # 3. Effective interventions
        effective = self.get_effective_interventions()
        if effective:
            lines.append("\n=== INTERVENTIONS THAT WORKED ===")
            for i in effective[:max_items // 2]:
                status = i.properties.get("validation_status", "?")
                lines.append(f"  [{status.upper()}] {i.label[:100]}")

        # 4. Failed interventions (important — don't propose the same thing)
        failed = self.get_failed_interventions()
        if failed:
            lines.append("\n=== INTERVENTIONS THAT DID NOT WORK ===")
            for i in failed[:max_items // 2]:
                status = i.properties.get("validation_status", "?")
                lines.append(f"  [{status.upper()}] {i.label[:100]}")

        # 5. Failure class coverage
        all_failures = self.get_nodes_by_type(NodeType.FAILURE)
        if all_failures:
            class_counts: dict[str, int] = {}
            for f in all_failures:
                fc = f.properties.get("failure_class", "UNKNOWN")
                class_counts[fc] = class_counts.get(fc, 0) + 1

            lines.append("\n=== FAILURE CLASS COVERAGE ===")
            for fc, count in sorted(class_counts.items()):
                lines.append(f"  {fc}: {count} findings")

        if not lines or lines == ["=== No previous hypotheses tested ==="]:
            return "  None — this is the first research cycle."

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Overall graph statistics."""
        return {
            "total_nodes": self.node_count,
            "total_edges": self.edge_count,
            "cycles": len(self.get_nodes_by_type(NodeType.CYCLE)),
            "hypotheses": len(self.get_nodes_by_type(NodeType.HYPOTHESIS)),
            "failures": len(self.get_nodes_by_type(NodeType.FAILURE)),
            "interventions": len(self.get_nodes_by_type(NodeType.INTERVENTION)),
            "experiments": len(self.get_nodes_by_type(NodeType.EXPERIMENT)),
            "confirmed_failures": len(self.get_confirmed_failures()),
            "effective_interventions": len(self.get_effective_interventions()),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _severity_distribution(failure_nodes: list[MemoryNode]) -> dict[str, int]:
        dist: dict[str, int] = {}
        for n in failure_nodes:
            if n.properties.get("hypothesis_confirmed"):
                sev = n.properties.get("severity", "?")
                dist[sev] = dist.get(sev, 0) + 1
        return dist
