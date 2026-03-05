"""Findings screen — filterable failures DataTable with detail panel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Select, Static


class DetailPanel(Static):
    """Shows full evidence and sample outputs for the selected failure."""

    DEFAULT_CSS = """
    DetailPanel {
        height: auto;
        min-height: 5;
        max-height: 14;
        padding: 1 2;
        margin: 1 0 0 0;
        border: solid $accent;
        overflow-y: auto;
    }
    """


class FindingsScreen(Screen):
    """Filterable failures browser with detail panel."""

    BINDINGS = [
        ("d", "app.action_show_dashboard()", "Dashboard"),
        ("h", "app.action_show_hypotheses()", "Hypotheses"),
        ("q", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    FindingsScreen {
        layout: vertical;
    }
    #filter-bar {
        height: 3;
        padding: 0 1;
    }
    #findings-table {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._all_failures: list = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="filter-bar"):
            yield Select(
                [("All", "all"), ("S0+", "S0+"), ("S1+", "S1+"), ("S2+", "S2+"), ("S3+", "S3+"), ("S4+", "S4+")],
                value="all",
                id="severity-filter",
                prompt="Severity",
            )
            yield Select(
                [("All", "all"), ("REASONING", "REASONING"), ("LONG_CONTEXT", "LONG_CONTEXT"),
                 ("TOOL_USE", "TOOL_USE"), ("FEEDBACK_LOOP", "FEEDBACK_LOOP"),
                 ("DEPLOYMENT", "DEPLOYMENT"), ("SECURITY", "SECURITY")],
                value="all",
                id="class-filter",
                prompt="Class",
            )
        yield DataTable(id="findings-table")
        yield DetailPanel(id="detail-panel")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#findings-table", DataTable)
        table.add_columns("Severity", "Class", "Subtype", "Rate", "Evidence", "Cycle")
        table.cursor_type = "row"
        await self._refresh_data()

    async def on_screen_resume(self) -> None:
        await self._refresh_data()

    async def _refresh_data(
        self,
        min_severity: str | None = None,
        failure_class: str | None = None,
    ) -> None:
        """Load failures from DB and populate the table."""
        from sentinel.reporting.queries import get_failures

        try:
            self._all_failures = await get_failures(
                min_severity=min_severity,
                failure_class=failure_class,
            )
        except RuntimeError:
            self._all_failures = []

        self._populate_table()

    def _populate_table(self) -> None:
        table = self.query_one("#findings-table", DataTable)
        table.clear()
        for f in self._all_failures:
            evidence = f.evidence or ""
            truncated = (evidence[:57] + "...") if len(evidence) > 60 else evidence
            table.add_row(
                f.severity,
                f.failure_class,
                f.failure_subtype or "-",
                f"{f.failure_rate:.0%}",
                truncated,
                f.cycle_id or "-",
            )

        # Clear detail panel
        self.query_one("#detail-panel", DetailPanel).update(
            "[dim]Select a row to see details[/dim]"
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Show full detail for the selected failure."""
        idx = event.cursor_row
        if 0 <= idx < len(self._all_failures):
            f = self._all_failures[idx]
            detail = (
                f"[bold]Severity:[/bold] {f.severity}  "
                f"[bold]Class:[/bold] {f.failure_class}  "
                f"[bold]Subtype:[/bold] {f.failure_subtype or '-'}\n"
                f"[bold]Rate:[/bold] {f.failure_rate:.0%}  "
                f"[bold]Cycle:[/bold] {f.cycle_id or '-'}\n\n"
                f"[bold]Evidence:[/bold]\n{f.evidence}\n\n"
                f"[bold]Sample failure output:[/bold]\n{f.sample_failure_output or '-'}\n"
                f"[bold]Sample correct output:[/bold]\n{f.sample_correct_output or '-'}"
            )
            self.query_one("#detail-panel", DetailPanel).update(detail)

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Re-filter when a dropdown changes."""
        sev_select = self.query_one("#severity-filter", Select)
        cls_select = self.query_one("#class-filter", Select)

        min_sev = None if sev_select.value == "all" else str(sev_select.value)
        fc = None if cls_select.value == "all" else str(cls_select.value)

        await self._refresh_data(min_severity=min_sev, failure_class=fc)
