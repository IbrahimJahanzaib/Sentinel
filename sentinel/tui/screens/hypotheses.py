"""Hypotheses screen — filterable hypotheses DataTable with detail panel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Select, Static


class DetailPanel(Static):
    """Shows full description and rationale for the selected hypothesis."""

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


class HypothesesScreen(Screen):
    """Filterable hypotheses browser with detail panel."""

    BINDINGS = [
        ("d", "app.action_show_dashboard()", "Dashboard"),
        ("f", "app.action_show_findings()", "Findings"),
        ("q", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    HypothesesScreen {
        layout: vertical;
    }
    #filter-bar {
        height: 3;
        padding: 0 1;
    }
    #hypotheses-table {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._all_hypotheses: list = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="filter-bar"):
            yield Select(
                [("All", "all"), ("untested", "untested"),
                 ("confirmed", "confirmed"), ("rejected", "rejected"),
                 ("skipped", "skipped")],
                value="all",
                id="status-filter",
                prompt="Status",
            )
        yield DataTable(id="hypotheses-table")
        yield DetailPanel(id="hyp-detail-panel")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#hypotheses-table", DataTable)
        table.add_columns("Status", "Class", "Severity", "Description", "Cycle")
        table.cursor_type = "row"
        await self._refresh_data()

    async def on_screen_resume(self) -> None:
        await self._refresh_data()

    async def _refresh_data(self, status: str | None = None) -> None:
        """Load hypotheses from DB and populate the table."""
        from sentinel.reporting.queries import get_hypotheses

        try:
            self._all_hypotheses = await get_hypotheses(status=status)
        except RuntimeError:
            self._all_hypotheses = []

        self._populate_table()

    def _populate_table(self) -> None:
        table = self.query_one("#hypotheses-table", DataTable)
        table.clear()
        for h in self._all_hypotheses:
            desc = h.description or ""
            truncated = (desc[:57] + "...") if len(desc) > 60 else desc
            table.add_row(
                h.status,
                h.failure_class,
                h.expected_severity,
                truncated,
                h.cycle_id or "-",
            )

        self.query_one("#hyp-detail-panel", DetailPanel).update(
            "[dim]Select a row to see details[/dim]"
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Show full detail for the selected hypothesis."""
        idx = event.cursor_row
        if 0 <= idx < len(self._all_hypotheses):
            h = self._all_hypotheses[idx]
            detail = (
                f"[bold]Status:[/bold] {h.status}  "
                f"[bold]Class:[/bold] {h.failure_class}  "
                f"[bold]Severity:[/bold] {h.expected_severity}\n"
                f"[bold]Cycle:[/bold] {h.cycle_id or '-'}\n\n"
                f"[bold]Description:[/bold]\n{h.description}\n\n"
                f"[bold]Rationale:[/bold]\n{h.rationale or '-'}"
            )
            self.query_one("#hyp-detail-panel", DetailPanel).update(detail)

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Re-filter when the status dropdown changes."""
        status_select = self.query_one("#status-filter", Select)
        status = None if status_select.value == "all" else str(status_select.value)
        await self._refresh_data(status=status)
