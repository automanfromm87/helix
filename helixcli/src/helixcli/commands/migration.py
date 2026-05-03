"""`helixcli migration <name>` — alembic revision wrapper.

A thin layer over `cd apps/api && uv run alembic revision
--autogenerate -m "<name>"`. Why a wrapper:
  * Predictable cwd — agent doesn't have to remember to `cd apps/api`.
  * Predictable env — alembic.ini's script_location is what the
    helixcli init template wrote.
  * Captures the new revision file path in the JSON output.
  * Auto-commit, same as the other generators.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from helixcli import git
from helixcli.errors import GeneratorFailed, NoManifest, StackMismatch
from helixcli.manifest import Manifest


def run(*, project_root: Path, name: str) -> dict:
    project_root = project_root.resolve()
    if not Manifest.exists(project_root):
        raise NoManifest(str(project_root))
    manifest = Manifest.load(project_root)
    if manifest.stack.backend is None:
        raise StackMismatch(
            "Project was initialised --frontend-only; can't run migrations."
        )

    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise GeneratorFailed(
            "migration", f"name {name!r} must be snake_case ([a-z][a-z0-9_]*)",
        )

    api = project_root / "apps" / "api"
    versions_before = _list_versions(api)

    try:
        proc = subprocess.run(
            ["uv", "run", "alembic", "revision", "--autogenerate", "-m", name],
            cwd=str(api),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise GeneratorFailed(
            "migration", "uv is not on $PATH (sandbox image must ship uv)",
        ) from e

    if proc.returncode != 0:
        raise GeneratorFailed(
            "migration",
            f"alembic exit {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}",
        )

    versions_after = _list_versions(api)
    new_files = [p for p in versions_after if p not in versions_before]
    sha = git.commit_all(project_root, f"helixcli migration {name}")

    return {
        "command": "migration",
        "name": name,
        "created": [str(p.relative_to(project_root)) for p in new_files],
        "alembic_stdout": proc.stdout,
        "git_sha": sha,
    }


def _list_versions(api: Path) -> list[Path]:
    versions = api / "migrations" / "versions"
    if not versions.exists():
        return []
    return sorted(p for p in versions.iterdir() if p.suffix == ".py")
