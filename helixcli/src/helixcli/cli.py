"""CLI entry point. Each subcommand lives in `helixcli.commands.*`.

Output convention: every command prints a single JSON object on stdout
on success (so the agent's tool wrapper can parse it), and writes
human-readable diagnostics to stderr. Exit codes per SPEC.md §4.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from helixcli.commands import component as component_cmd
from helixcli.commands import endpoint as endpoint_cmd
from helixcli.commands import hook as hook_cmd
from helixcli.commands import init as init_cmd
from helixcli.commands import install as install_cmd
from helixcli.commands import migration as migration_cmd
from helixcli.commands import model as model_cmd
from helixcli.commands import page as page_cmd
from helixcli.commands import up as up_cmd
from helixcli.errors import HelixCliError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Deterministic project scaffolder for the Helix sandbox.",
)


def _emit(payload: dict) -> None:
    """Single point where success output lands on stdout. Newline at
    the end so streaming consumers (the tool wrapper) can split on \\n."""
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


def _fail(err: HelixCliError) -> None:
    sys.stderr.write(f"helixcli: {err}\n")
    raise typer.Exit(code=err.exit_code)


@app.command("init")
def init_command(
    name: Optional[str] = typer.Argument(
        None,
        help=(
            "Project name. With a name, creates ./<name>/ as the project "
            "root (cargo / pnpm convention). With '.' or no arg, uses the "
            "current directory."
        ),
    ),
    frontend_only: bool = typer.Option(False, "--frontend-only"),
    backend_only: bool = typer.Option(False, "--backend-only"),
    db: str = typer.Option("postgres", "--db", help="postgres or sqlite"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Scaffold a new Helix project (web + api by default)."""
    if frontend_only and backend_only:
        sys.stderr.write("--frontend-only and --backend-only are mutually exclusive\n")
        raise typer.Exit(code=2)
    if db not in ("postgres", "sqlite"):
        sys.stderr.write(f"--db must be 'postgres' or 'sqlite', got {db!r}\n")
        raise typer.Exit(code=2)

    invocation_cwd = Path.cwd()
    if name in (None, "", "."):
        project_root = invocation_cwd
        project_name = invocation_cwd.name
    else:
        project_root = invocation_cwd / name
        project_name = name

    try:
        result = init_cmd.run(
            project_root=project_root,
            name=project_name,
            frontend=not backend_only,
            backend=not frontend_only,
            db=db,  # type: ignore[arg-type]
            force=force,
        )
    except HelixCliError as e:
        _fail(e)
    _emit(result)


@app.command("page")
def page_command(
    name: str = typer.Argument(..., help="Component name in PascalCase, e.g. 'Login'."),
) -> None:
    """Add a new page to the frontend (component + test + route)."""
    try:
        result = page_cmd.run(project_root=Path.cwd(), name=name)
    except HelixCliError as e:
        _fail(e)
    _emit(result)


@app.command("endpoint")
def endpoint_command(
    method: str = typer.Argument(..., help="HTTP method: GET, POST, PATCH, DELETE."),
    path: str = typer.Argument(..., help="Route path, e.g. '/api/v1/auth/login'."),
    auth: str = typer.Option(
        "required", "--auth", help="'required' or 'public'.",
    ),
) -> None:
    """Add a new backend endpoint (handler + schema + test)."""
    if method.upper() not in ("GET", "POST", "PATCH", "DELETE", "PUT"):
        sys.stderr.write(f"unsupported method {method!r}\n")
        raise typer.Exit(code=2)
    if auth not in ("required", "public"):
        sys.stderr.write(f"--auth must be 'required' or 'public', got {auth!r}\n")
        raise typer.Exit(code=2)
    try:
        result = endpoint_cmd.run(
            project_root=Path.cwd(),
            method=method.upper(),
            path=path,
            auth=auth,  # type: ignore[arg-type]
        )
    except HelixCliError as e:
        _fail(e)
    _emit(result)


@app.command("migration")
def migration_command(
    name: str = typer.Argument(..., help="Short snake_case name, e.g. 'init_users'."),
) -> None:
    """Wrapper around `alembic revision --autogenerate` inside apps/api."""
    try:
        result = migration_cmd.run(project_root=Path.cwd(), name=name)
    except HelixCliError as e:
        _fail(e)
    _emit(result)


@app.command("component")
def component_command(
    name: str = typer.Argument(
        ..., help="Component name in PascalCase, e.g. 'PostCard'.",
    ),
) -> None:
    """Add a frontend React component (no router wiring).

    For routed pages use `helixcli page`. This command is for
    presentational components mounted by other components.
    """
    try:
        result = component_cmd.run(project_root=Path.cwd(), name=name)
    except HelixCliError as e:
        _fail(e)
    _emit(result)


@app.command("hook")
def hook_command(
    name: str = typer.Argument(
        ..., help="Hook noun in PascalCase (without leading 'use'), e.g. 'Posts'.",
    ),
) -> None:
    """Add a custom React hook. The generator prepends `use` — pass
    'Posts' to get `usePosts.ts`."""
    try:
        result = hook_cmd.run(project_root=Path.cwd(), name=name)
    except HelixCliError as e:
        _fail(e)
    _emit(result)


@app.command("model")
def model_command(
    name: str = typer.Argument(
        ..., help="Model class name in PascalCase, e.g. 'User'.",
    ),
) -> None:
    """Add a SQLAlchemy ORM model. File path is snake_case
    (`user.py`); table name is plural snake_case (`users`).

    The model is registered in `apps/api/app/models/__init__.py` so
    Alembic's autogenerate sees it; run `helix_scaffold migration
    init_<name>` afterwards to create the migration.
    """
    try:
        result = model_cmd.run(project_root=Path.cwd(), name=name)
    except HelixCliError as e:
        _fail(e)
    _emit(result)


@app.command("install")
def install_command() -> None:
    """Install dependencies for whichever apps the manifest declares.

    Runs `npm install` at the project root (the npm workspace covers
    apps/web) and `uv sync` in apps/api. Streams install logs to your
    terminal; the final JSON line is what tooling parses.
    """
    try:
        result = install_cmd.run(project_root=Path.cwd())
    except HelixCliError as e:
        _fail(e)
    _emit(result)


@app.command("up")
def up_command() -> None:
    """Start dev servers in the background.

    Spawns `npm run dev --workspace apps/web` and/or `uv run fastapi
    dev` detached. PIDs are recorded under `.helix/pids/`, logs under
    `.helix/logs/`. Idempotent: if a server is already up (per the
    recorded PID), reports it as already-running rather than starting
    a duplicate.

    To stop: `helixcli down`. To watch logs: `tail -f .helix/logs/web.log`.
    """
    try:
        result = up_cmd.run_up(project_root=Path.cwd())
    except HelixCliError as e:
        _fail(e)
    _emit(result)


@app.command("down")
def down_command() -> None:
    """Stop dev servers started by `helixcli up`.

    SIGTERM first, then SIGKILL after a short grace period. Targets
    the process group so node / uvicorn child processes go down with
    their parent. Cleans up `.helix/pids/`.
    """
    try:
        result = up_cmd.run_down(project_root=Path.cwd())
    except HelixCliError as e:
        _fail(e)
    _emit(result)
