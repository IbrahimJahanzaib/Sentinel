"""Sentinel — Autonomous AI reliability research agent."""

from __future__ import annotations

__version__ = "0.1.0"

from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .config.modes import Mode
    from .config.settings import SentinelSettings


async def create_sentinel(
    mode: "Mode | str | None" = None,
    db_url: Optional[str] = None,
    config_path: Optional[str] = None,
) -> "Sentinel":
    """Factory function — create and initialise a Sentinel instance.

    Parameters
    ----------
    mode:
        Operating mode (LAB, SHADOW, PRODUCTION). Overrides config file if provided.
    db_url:
        Database URL. Overrides config file if provided.
    config_path:
        Path to ``.sentinel/config.yaml``. Uses auto-discovery if omitted.

    Returns
    -------
    Sentinel
        Ready-to-use Sentinel instance with DB initialised.
    """
    from pathlib import Path
    from .config.settings import load_settings
    from .config.modes import Mode as ModeEnum
    from .db.connection import init_db

    settings = load_settings(Path(config_path) if config_path else None)

    if mode is not None:
        if isinstance(mode, str):
            mode = ModeEnum(mode.lower())
        settings.mode = mode

    if db_url is not None:
        settings.database.url = db_url

    await init_db(settings.database.url, echo=settings.database.echo)

    return Sentinel(settings=settings)


class Sentinel:
    """Main Sentinel orchestration object returned by ``create_sentinel``."""

    def __init__(self, settings: "SentinelSettings") -> None:
        self.settings = settings
        self.mode = settings.mode

    async def research_cycle(
        self,
        target: "Any",
        focus: Optional[str] = None,
        max_hypotheses: Optional[int] = None,
        max_experiments: Optional[int] = None,
        system_description: Optional[str] = None,
    ) -> "Any":
        """Run a full research cycle against a target system.

        Parameters
        ----------
        target:
            A TargetSystem implementation — the system being tested.
        focus:
            Natural language or failure class to focus on.
        max_hypotheses / max_experiments:
            Override config defaults.
        system_description:
            Override the target's own description.

        Returns
        -------
        CycleResult
        """
        from .core.control_plane import ControlPlane
        from .core.cost_tracker import CostTracker
        from .integrations.model_client import build_default_client

        tracker = CostTracker(budget_usd=self.settings.experiments.cost_limit_usd)
        client = build_default_client(self.settings, tracker)

        plane = ControlPlane(
            settings=self.settings,
            client=client,
            target=target,
            tracker=tracker,
        )
        return await plane.research_cycle(
            focus=focus,
            max_hypotheses=max_hypotheses,
            max_experiments=max_experiments,
            system_description=system_description,
        )

    async def close(self) -> None:
        """Clean up resources."""
        from .db.connection import close_db
        await close_db()

    def __repr__(self) -> str:
        return f"Sentinel(mode={self.mode.value}, db={self.settings.database.url!r})"
