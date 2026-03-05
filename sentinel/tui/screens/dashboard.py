"""Dashboard screen — cycle history, failure summary, and key metrics."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static


class StatsPanel(Static):
    """Displays aggregate statistics."""

    DEFAULT_CSS = """
    StatsPanel {
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        border: solid $accent;
    }
    """


class SeverityPanel(Static):
    """Displays severity distribution."""

    DEFAULT_CSS = """
    SeverityPanel {
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        border: solid $secondary;
    }
    """


class DashboardScreen(Screen):
    """Main dashboard showing cycle history, failure stats, and severity distribution."""

    BINDINGS = [
        ("f", "app.switch_mode('findings')", "Findings"),
        ("h", "app.switch_mode('hypotheses')", "Hypotheses"),
        ("q", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }
    #top-row {
        height: auto;
        max-height: 12;
    }
    #stats-panel {
        width: 1fr;
    }
    #severity-panel {
        width: 1fr;
    }
    #cycles-table {
        height: 1fr;
        margin: 0 0 0 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top-row"):
            yield StatsPanel(id="stats-panel")
            yield SeverityPanel(id="severity-panel")
        yield DataTable(id="cycles-table")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#cycles-table", DataTable)
        table.add_columns("ID", "Focus", "Failures", "Cost", "Date")
        table.cursor_type = "row"
        await self._refresh_data()

    async def on_screen_resume(self) -> None:
        await self._refresh_data()

    async def _refresh_data(self) -> None:
        """Load data from the DB and update all widgets."""
        from sentinel.reporting.queries import (
            get_cycles,
            get_failures,
            get_interventions,
        )

        try:
            cycles = await get_cycles(limit=50)
            failures = await get_failures()
            interventions = await get_interventions()
        except RuntimeError:
            # DB not initialised — show empty state
            cycles, failures, interventions = [], [], []

        # ── Stats panel ──────────────────────────────────────────
        total_cost = sum(c.total_cost_usd for c in cycles)
        mode = self.app.sentinel_mode if hasattr(self.app, "sentinel_mode") else "LAB"

        stats_text = (
            f"[bold]Mode:[/bold] {mode}\n"
            f"[bold]Cycles:[/bold] {len(cycles)}\n"
            f"[bold]Failures:[/bold] {len(failures)}\n"
            f"[bold]Interventions:[/bold] {len(interventions)}\n"
            f"[bold]Total cost:[/bold] ${total_cost:.4f}"
        )
        self.query_one("#stats-panel", StatsPanel).update(stats_text)

        # ── Severity distribution ────────────────────────────────
        sev_counts: dict[str, int] = {"S0": 0, "S1": 0, "S2": 0, "S3": 0, "S4": 0}
        for f in failures:
            if f.severity in sev_counts:
                sev_counts[f.severity] += 1

        sev_lines = " | ".join(f"[bold]{k}[/bold]: {v}" for k, v in sev_counts.items())
        self.query_one("#severity-panel", SeverityPanel).update(
            f"[bold]Severity Distribution[/bold]\n{sev_lines}"
        )

        # ── Cycles table ─────────────────────────────────────────
        table = self.query_one("#cycles-table", DataTable)
        table.clear()
        for c in cycles:
            date_str = c.started_at.strftime("%Y-%m-%d %H:%M") if c.started_at else "-"
            table.add_row(
                c.id,
                c.focus or "all",
                str(c.failures_found),
                f"${c.total_cost_usd:.4f}",
                date_str,
            )
