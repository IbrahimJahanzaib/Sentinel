"""Alerters for dispatching findings from the Gateway Monitor."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from sentinel.integrations.gateway_plugin.models import AlertFinding
from sentinel.taxonomy.failure_types import Severity

logger = logging.getLogger(__name__)

# Severity ordering for min_severity filtering
_SEVERITY_ORDER = {s.value: i for i, s in enumerate(Severity)}


def _passes_severity(finding: AlertFinding, min_severity: str) -> bool:
    """Return True if the finding's severity meets or exceeds min_severity."""
    finding_rank = _SEVERITY_ORDER.get(finding.severity, 0)
    min_rank = _SEVERITY_ORDER.get(min_severity, 0)
    return finding_rank >= min_rank


class ConsoleAlerter:
    """Prints findings as Rich Panels to the console."""

    def __init__(self, min_severity: str = "S0") -> None:
        self.min_severity = min_severity

    async def alert(self, finding: AlertFinding) -> None:
        if not _passes_severity(finding, self.min_severity):
            return

        try:
            from rich.console import Console
            from rich.panel import Panel

            console = Console(stderr=True)
            color = {"S4": "red", "S3": "yellow", "S2": "cyan", "S1": "blue"}.get(
                finding.severity, "dim"
            )
            console.print(
                Panel(
                    f"[bold]{finding.summary}[/bold]\n"
                    f"Severity: {finding.severity} | Class: {finding.failure_class}\n"
                    f"Evidence: {finding.evidence}",
                    title=f"[{color}]Alert: {finding.severity}[/{color}]",
                    border_style=color,
                )
            )
        except ImportError:
            print(f"[ALERT {finding.severity}] {finding.summary}")


class FileAlerter:
    """Appends findings as markdown to a file."""

    def __init__(
        self, path: str | Path, min_severity: str = "S0"
    ) -> None:
        self.path = Path(path)
        self.min_severity = min_severity
        self._lock = asyncio.Lock()

    async def alert(self, finding: AlertFinding) -> None:
        if not _passes_severity(finding, self.min_severity):
            return

        entry = (
            f"## [{finding.severity}] {finding.summary}\n"
            f"- **Class:** {finding.failure_class}\n"
            f"- **Time:** {finding.timestamp.isoformat()}\n"
            f"- **Evidence:** {finding.evidence}\n\n"
        )

        async with self._lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, self._write_sync, entry
            )

    def _write_sync(self, entry: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(entry)


class WebhookAlerter:
    """POSTs findings as JSON to a webhook URL."""

    def __init__(
        self,
        url: str,
        *,
        min_severity: str = "S0",
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.url = url
        self.min_severity = min_severity
        self.headers = headers or {}
        self.timeout = timeout

    async def alert(self, finding: AlertFinding) -> None:
        if not _passes_severity(finding, self.min_severity):
            return

        import httpx

        payload = finding.model_dump(mode="json")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                )
                resp.raise_for_status()
        except Exception:
            logger.warning("Webhook alert to %s failed", self.url, exc_info=True)
