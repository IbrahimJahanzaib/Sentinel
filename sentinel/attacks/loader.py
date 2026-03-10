"""Loads and filters attack probes from YAML files."""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import AttackProbe


class ProbeLoader:
    """Load attack probes from a directory of YAML files."""

    def __init__(self, probes_dir: str | None = None) -> None:
        self.probes_dir = Path(probes_dir) if probes_dir else Path(__file__).parent / "probes"

    def load_all(self) -> list[AttackProbe]:
        """Load every probe from every category."""
        probes = []
        for yaml_file in sorted(self.probes_dir.rglob("*.yaml")):
            probe = self._load_file(yaml_file)
            if probe:
                probes.append(probe)
        return probes

    def load_category(self, category: str) -> list[AttackProbe]:
        """Load all probes from one category folder."""
        cat_dir = self.probes_dir / category
        if not cat_dir.exists():
            available = self.list_categories()
            raise ValueError(f"Category '{category}' not found. Available: {available}")
        probes = []
        for yaml_file in sorted(cat_dir.glob("*.yaml")):
            probe = self._load_file(yaml_file)
            if probe:
                probes.append(probe)
        return probes

    def load_by_severity(self, min_severity: str) -> list[AttackProbe]:
        """Load all probes at or above a severity threshold."""
        order = {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4}
        min_level = order.get(min_severity, 0)
        return [p for p in self.load_all() if order.get(p.severity, 0) >= min_level]

    def load_by_ids(self, probe_ids: list[str]) -> list[AttackProbe]:
        """Load specific probes by their IDs."""
        all_probes = {p.id: p for p in self.load_all()}
        results = []
        for pid in probe_ids:
            if pid not in all_probes:
                raise ValueError(f"Probe '{pid}' not found. Available: {sorted(all_probes.keys())}")
            results.append(all_probes[pid])
        return results

    def load_by_tags(self, tags: list[str]) -> list[AttackProbe]:
        """Load probes that have ANY of the specified tags."""
        tag_set = set(tags)
        return [p for p in self.load_all() if tag_set.intersection(set(p.tags))]

    def list_categories(self) -> list[str]:
        """List all category folder names."""
        return sorted(
            d.name for d in self.probes_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        )

    def count(self) -> dict[str, int]:
        """Count probes per category and total."""
        counts: dict[str, int] = {}
        for cat in self.list_categories():
            counts[cat] = len(list((self.probes_dir / cat).glob("*.yaml")))
        counts["total"] = sum(v for k, v in counts.items() if k != "total")
        return counts

    def _load_file(self, path: Path) -> AttackProbe | None:
        """Load and validate a single YAML probe file."""
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            return AttackProbe(**data)
        except Exception as e:
            print(f"Warning: Failed to load {path}: {e}")
            return None
