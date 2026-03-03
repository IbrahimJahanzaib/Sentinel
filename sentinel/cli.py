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
@click.option("--target", default=None, help="Target system name or path.")
def research(focus: str, max_hypotheses: int, target: str) -> None:
    """Run a research cycle (Phase 4)."""
    console.print("[yellow]The research command will be available after Phase 4.[/yellow]")


@cli.command()
@click.option("--format", "fmt", default="markdown", type=click.Choice(["markdown", "json"]))
@click.option("--output", default=None, help="Output file path (defaults to stdout).")
def report(fmt: str, output: str) -> None:
    """Generate a findings report (Phase 7)."""
    console.print("[yellow]The report command will be available after Phase 7.[/yellow]")


@cli.command()
@click.option("--severity", default=None, help="Filter by minimum severity, e.g. S2+.")
@click.option("--class", "failure_class", default=None, help="Filter by failure class.")
def failures(severity: str, failure_class: str) -> None:
    """List discovered failures (Phase 7)."""
    console.print("[yellow]The failures command will be available after Phase 7.[/yellow]")


@cli.command()
@click.option("--status", default=None, help="Filter by status: untested, confirmed, rejected.")
def hypotheses(status: str) -> None:
    """List hypotheses (Phase 7)."""
    console.print("[yellow]The hypotheses command will be available after Phase 7.[/yellow]")


@cli.command()
def tui() -> None:
    """Launch the interactive terminal UI (Phase 8)."""
    console.print("[yellow]The TUI will be available after Phase 8.[/yellow]")
