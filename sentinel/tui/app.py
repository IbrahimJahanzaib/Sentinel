"""Sentinel TUI — main Textual application."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding

from sentinel.tui.screens.dashboard import DashboardScreen
from sentinel.tui.screens.findings import FindingsScreen
from sentinel.tui.screens.hypotheses import HypothesesScreen


class SentinelApp(App):
    """Interactive terminal UI for Sentinel."""

    TITLE = "Sentinel"
    SUB_TITLE = "AI Reliability Research Agent"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("d", "show_dashboard", "Dashboard", show=True),
        Binding("f", "show_findings", "Findings", show=True),
        Binding("h", "show_hypotheses", "Hypotheses", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(
        self,
        db_url: str | None = None,
        mode: str = "LAB",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._db_url = db_url
        self.sentinel_mode = mode.upper()
        self._current_screen_name = "dashboard"

    async def on_mount(self) -> None:
        """Initialise the DB connection and show the dashboard."""
        if self._db_url:
            from sentinel.db.connection import init_db

            try:
                await init_db(self._db_url, echo=False)
            except Exception:
                pass  # DB may already be initialised

        await self.push_screen(DashboardScreen())

    async def on_unmount(self) -> None:
        """Close the DB connection on exit."""
        from sentinel.db.connection import close_db

        try:
            await close_db()
        except Exception:
            pass

    def action_show_dashboard(self) -> None:
        if self._current_screen_name != "dashboard":
            self.pop_screen()
            self.push_screen(DashboardScreen())
            self._current_screen_name = "dashboard"

    def action_show_findings(self) -> None:
        if self._current_screen_name != "findings":
            self.pop_screen()
            self.push_screen(FindingsScreen())
            self._current_screen_name = "findings"

    def action_show_hypotheses(self) -> None:
        if self._current_screen_name != "hypotheses":
            self.pop_screen()
            self.push_screen(HypothesesScreen())
            self._current_screen_name = "hypotheses"
