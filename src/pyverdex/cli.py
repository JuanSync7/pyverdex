"""pyverdex command-line interface.

    pyverdex run [PROJECT_ROOT]      run the verification engine
    pyverdex resume                  resume after a human gate
    pyverdex version

``run`` walks the engine graph. When a gated stage raises an interrupt the run
pauses; pass ``--yes`` to auto-approve all gates (CI), or resume later with
``pyverdex resume``.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import Config, parse_levels
from .graph import build_engine, initial_state, make_checkpointer

app = typer.Typer(add_completion=False, help="Multi-dimensional test-coverage engine.")
console = Console()


def _load_config(config: Optional[str], project_root: Optional[str],
                 source: Optional[str], test: Optional[str],
                 level: Optional[str] = None, apply: bool = False) -> Config:
    cfg = Config.load(config)
    if project_root:
        cfg.project_root = project_root
    if source:
        cfg.paths.source_root = source
    if test:
        cfg.paths.test_root = test
    if level:
        # restrict to the stages the requested test level(s) need (orthogonal to
        # coverage tiers). Bad tokens raise a clean typer error, not a traceback.
        try:
            cfg.apply_levels(parse_levels(level))
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    if apply:
        # close the loop end-to-end: generate writes+mutates, integrate writes+checks
        cfg.generate.apply = True
        cfg.integrate.apply = True
    cfg.ensure_dirs()
    return cfg


def _print_log(state: dict) -> None:
    for line in state.get("log", []):
        console.print(f"  [dim]·[/dim] {line}")
    for err in state.get("errors", []):
        console.print(f"  [red]![/red] {err}")


def _print_summary(state: dict) -> None:
    uc = state.get("unified_coverage")
    if not uc:
        console.print("[yellow]No unified report produced.[/yellow]")
        return
    table = Table(title="Coverage dimensions", show_lines=False)
    table.add_column("Dimension")
    table.add_column("Status")
    table.add_column("Headline")
    colour = {"pass": "green", "fail": "red", "warn": "yellow", "not_run": "dim", "unknown": "dim"}
    for d in uc.get("dimensions", []):
        s = d["status"]
        table.add_row(d["name"], f"[{colour.get(s,'white')}]{s}[/]", d["headline"])
    console.print(table)
    console.print(f"Overall: [bold]{uc.get('overall_status')}[/bold]  "
                  f"· report: {state.get('report_path')}")


def _drive(cfg: Config, first_input, thread: str, assume_yes: bool) -> dict:
    from langgraph.types import Command

    checkpointer = make_checkpointer(cfg)
    engine = build_engine(cfg, checkpointer=checkpointer)
    run_cfg = {"configurable": {"thread_id": thread}}

    payload = first_input
    while True:
        state = engine.invoke(payload, run_cfg)
        snap = engine.get_state(run_cfg)
        if not snap.next:
            return state  # finished
        # a gate interrupted the run
        pending = []
        for task in snap.tasks:
            for itr in getattr(task, "interrupts", []) or []:
                pending.append(itr.value)
        gate = pending[0] if pending else {"stage": "?"}
        console.print(f"\n[bold yellow]GATE[/bold yellow] stage="
                      f"{gate.get('stage')} :: {gate.get('gate')}")
        if assume_yes:
            console.print("  auto-approving (--yes)")
            payload = Command(resume={"approve": True})
            continue
        console.print(f"  paused. Resume with: [bold]pyverdex resume "
                      f"--thread {thread} --approve[/bold]  (or --reject)")
        return state


@app.command()
def run(
    project_root: Optional[str] = typer.Argument(None, help="Project to verify."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config YAML."),
    source: Optional[str] = typer.Option(None, "--source", help="Source root."),
    test: Optional[str] = typer.Option(None, "--test", help="Test root."),
    thread: str = typer.Option("pyverdex", "--thread", help="Run/thread id."),
    level: Optional[str] = typer.Option(
        None, "--level",
        help="Restrict to test level(s), comma-separated: smoke, unit, integration, "
             "e2e (e2e currently runs the integration pipeline). Omit to run every "
             "stage."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve all gates."),
    apply: bool = typer.Option(
        False, "--apply",
        help="Close the loop: write approved generated + integration tests to disk "
             "(default is propose-only)."),
) -> None:
    cfg = _load_config(config, project_root, source, test, level, apply)
    console.print(f"[bold]pyverdex[/bold] verifying [cyan]{cfg.abs_source_root}[/cyan]"
                  + (f"  [dim](level: {level})[/dim]" if level else "")
                  + ("  [dim](apply-mode)[/dim]" if apply else ""))
    state = _drive(cfg, initial_state(cfg), thread, yes)
    _print_log(state)
    _print_summary(state)


@app.command()
def resume(
    thread: str = typer.Option("pyverdex", "--thread", help="Run/thread id."),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
    project_root: Optional[str] = typer.Option(None, "--project-root"),
    approve: bool = typer.Option(False, "--approve", help="Approve the pending gate."),
    reject: bool = typer.Option(False, "--reject", help="Reject the pending gate."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve remaining gates."),
) -> None:
    from langgraph.types import Command

    cfg = _load_config(config, project_root, None, None)
    decision = {"approve": not reject and (approve or True)}
    if reject:
        decision = {"approve": False}
    state = _drive(cfg, Command(resume=decision), thread, yes)
    _print_log(state)
    _print_summary(state)


@app.command()
def serve(
    project_root: Optional[str] = typer.Argument(None, help="Default project to load."),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    allow_origin: list[str] = typer.Option(
        [], "--allow-origin",
        help="Extra origin allowed to reach the API (e.g. https://your.wiki). "
             "Loopback is always allowed; the bundled UI needs no flag.",
    ),
) -> None:
    """Launch the pyverdex web app (dashboard + web terminal)."""
    import uvicorn

    from .server import create_app

    default = str(project_root) if project_root else None
    app_ = create_app(default_project=default, host=host, allow_origins=list(allow_origin))
    console.print(f"[bold]pyverdex[/bold] web UI on http://{host}:{port}"
                  + (f"  (project: {default})" if default else ""))
    # The same-origin UI fetches this automatically; you only need it to point a
    # different-origin client (e.g. the hosted wiki) at this server.
    console.print(f"[dim]access token:[/dim] [bold]{app_.state.auth_token}[/bold]")
    uvicorn.run(app_, host=host, port=port, log_level="info")


@app.command()
def version() -> None:
    from importlib.metadata import version as v

    try:
        console.print(f"pyverdex {v('pyverdex')}")
    except Exception:
        console.print("pyverdex (dev)")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
