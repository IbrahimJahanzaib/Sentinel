"""Click-based CLI entry point for Sentinel."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

console = Console()


@click.group()
@click.version_option(package_name="sentinel")
def cli() -> None:
    """Sentinel — autonomous AI reliability research agent."""


# ---------------------------------------------------------------------------
# sentinel init
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--dir",
    "project_dir",
    default=".",
    show_default=True,
    help="Directory to initialise (defaults to current directory).",
)
@click.option("--force", is_flag=True, help="Overwrite existing config if present.")
def init(project_dir: str, force: bool) -> None:
    """Initialise a Sentinel project — creates .sentinel/config.yaml and the database."""
    from .config.settings import DEFAULT_CONFIG_YAML

    root = Path(project_dir).resolve()
    sentinel_dir = root / ".sentinel"
    config_file = sentinel_dir / "config.yaml"

    # Create .sentinel/ directory
    sentinel_dir.mkdir(parents=True, exist_ok=True)

    # Write config
    if config_file.exists() and not force:
        console.print(
            f"[yellow]Config already exists:[/yellow] {config_file}\n"
            "Use --force to overwrite."
        )
    else:
        config_file.write_text(DEFAULT_CONFIG_YAML)
        console.print(f"[green]Created[/green] {config_file}")

    # Initialise the database
    console.print("Initialising database...")
    asyncio.run(_init_db(root))

    console.print(
        Panel(
            "[bold green]Sentinel initialised.[/bold green]\n\n"
            f"Config:   [cyan]{config_file}[/cyan]\n"
            f"Database: [cyan]{root / 'sentinel.db'}[/cyan]\n\n"
            "Next steps:\n"
            "  1. Add your API keys to [cyan].env[/cyan] or set them as environment variables\n"
            "  2. Edit [cyan].sentinel/config.yaml[/cyan] to configure your target system\n"
            "  3. Run [bold]sentinel research --focus 'reasoning failures'[/bold]",
            title="[bold]sentinel init[/bold]",
        )
    )


async def _init_db(root: Path) -> None:
    """Async helper to initialise the database from the config."""
    import os
    os.chdir(root)

    from .config.settings import load_settings
    from .db.connection import init_db, close_db

    settings = load_settings()
    await init_db(settings.database.url, echo=False)
    await close_db()
    console.print(f"[green]Database ready:[/green] {settings.database.url}")


# ---------------------------------------------------------------------------
# Placeholder commands (implemented in later phases)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--focus", default=None, help="Natural language focus area for this cycle.")
@click.option("--max-hypotheses", default=None, type=int, help="Override max hypotheses per cycle.")
@click.option("--target", default=None, help="Target system description (uses built-in demo target).")
@click.option(
    "--approval",
    default="auto",
    type=click.Choice(["auto", "interactive", "auto_reject"]),
    help="Approval mode for this cycle.",
)
def research(focus: str | None, max_hypotheses: int | None, target: str | None, approval: str) -> None:
    """Run a full research cycle against a target system."""
    asyncio.run(_research(focus, max_hypotheses, target, approval))


async def _research(
    focus: str | None,
    max_hypotheses: int | None,
    target_desc: str | None,
    approval: str,
) -> None:
    """Async helper that runs a full research cycle."""
    from . import create_sentinel
    from .agents.demo_target import DemoTarget
    from .integrations.model_client import build_default_client
    from .core.cost_tracker import CostTracker

    description = target_desc or "A general-purpose LLM assistant"

    try:
        sentinel = await create_sentinel()

        # Override approval mode for CLI usage
        if approval == "auto":
            sentinel.settings.approval.mode = "auto_approve"
        else:
            sentinel.settings.approval.mode = approval

        # Build a client for the demo target
        tracker = CostTracker(budget_usd=sentinel.settings.experiments.cost_limit_usd)
        client = build_default_client(sentinel.settings, tracker)
        demo = DemoTarget(description=description, client=client)

        console.print(
            f"[bold]Starting research cycle[/bold]\n"
            f"  Target : [cyan]{description}[/cyan]\n"
            f"  Focus  : [cyan]{focus or 'all'}[/cyan]\n"
            f"  Approval: [cyan]{sentinel.settings.approval.mode}[/cyan]\n"
        )

        result = await sentinel.research_cycle(
            target=demo,
            focus=focus,
            max_hypotheses=max_hypotheses,
        )

        # Print summary
        console.print(Panel(
            f"[bold green]Cycle {result.cycle_id} complete[/bold green]\n\n"
            f"Hypotheses generated : {len(result.hypotheses)}\n"
            f"Failures found       : {len(result.failures)}\n"
            f"Confirmed failures   : {len(result.confirmed_failures)}\n"
            f"Interventions        : {len(result.interventions)}\n"
            f"Total cost           : ${result.cost_summary.get('total_cost_usd', 0):.4f}",
            title="[bold]Research Cycle Results[/bold]",
        ))

        await sentinel.close()

    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)


@cli.command()
@click.option("--format", "fmt", default="markdown", type=click.Choice(["markdown", "json"]))
@click.option("--output", "output_path", default=None, help="Output file path (defaults to stdout).")
def report(fmt: str, output_path: str | None) -> None:
    """Generate a findings report."""
    asyncio.run(_report(fmt, output_path))


async def _report(fmt: str, output_path: str | None) -> None:
    from .config.settings import load_settings
    from .db.connection import init_db, close_db
    from .reporting import (
        get_cycles, get_failures, get_interventions,
        generate_markdown_report, generate_json_report,
    )
    import json

    settings = load_settings()
    await init_db(settings.database.url, echo=False)
    try:
        cycles = await get_cycles()
        fails = await get_failures()
        interventions = await get_interventions()

        if fmt == "json":
            content = json.dumps(generate_json_report(cycles, fails, interventions), indent=2)
        else:
            content = generate_markdown_report(cycles, fails, interventions)

        if output_path:
            Path(output_path).write_text(content)
            console.print(f"[green]Report written to[/green] {output_path}")
        else:
            console.print(content)
    finally:
        await close_db()


@cli.command()
@click.option("--severity", default=None, help="Filter by minimum severity, e.g. S2+.")
@click.option("--class", "failure_class", default=None, help="Filter by failure class.")
def failures(severity: str | None, failure_class: str | None) -> None:
    """List discovered failures."""
    asyncio.run(_failures(severity, failure_class))


async def _failures(severity: str | None, failure_class: str | None) -> None:
    from rich.table import Table
    from .config.settings import load_settings
    from .db.connection import init_db, close_db
    from .reporting import get_failures

    settings = load_settings()
    await init_db(settings.database.url, echo=False)
    try:
        rows = await get_failures(min_severity=severity, failure_class=failure_class)
        if not rows:
            console.print("[dim]No failures found.[/dim]")
            return

        table = Table(title="Discovered Failures")
        table.add_column("Severity", style="bold")
        table.add_column("Class")
        table.add_column("Subtype")
        table.add_column("Rate")
        table.add_column("Evidence", max_width=60)
        table.add_column("Cycle")

        for f in rows:
            table.add_row(
                f.severity,
                f.failure_class,
                f.failure_subtype or "-",
                f"{f.failure_rate:.0%}",
                (f.evidence[:57] + "...") if len(f.evidence) > 60 else f.evidence,
                f.cycle_id or "-",
            )
        console.print(table)
    finally:
        await close_db()


@cli.command()
@click.option("--status", default=None, help="Filter by status: untested, confirmed, rejected.")
def hypotheses(status: str | None) -> None:
    """List hypotheses."""
    asyncio.run(_hypotheses(status))


async def _hypotheses(status: str | None) -> None:
    from rich.table import Table
    from .config.settings import load_settings
    from .db.connection import init_db, close_db
    from .reporting import get_hypotheses

    settings = load_settings()
    await init_db(settings.database.url, echo=False)
    try:
        rows = await get_hypotheses(status=status)
        if not rows:
            console.print("[dim]No hypotheses found.[/dim]")
            return

        table = Table(title="Hypotheses")
        table.add_column("Status", style="bold")
        table.add_column("Class")
        table.add_column("Severity")
        table.add_column("Description", max_width=60)
        table.add_column("Cycle")

        for h in rows:
            table.add_row(
                h.status,
                h.failure_class,
                h.expected_severity,
                (h.description[:57] + "...") if len(h.description) > 60 else h.description,
                h.cycle_id or "-",
            )
        console.print(table)
    finally:
        await close_db()


@cli.command()
def tui() -> None:
    """Launch the interactive terminal UI."""
    from .config.settings import load_settings
    from .tui import SentinelApp

    settings = load_settings()
    app = SentinelApp(db_url=settings.database.url, mode=settings.mode.value)
    app.run()
