"""`helixcli init` — scaffold the project root.

Implements SPEC.md §4 step-by-step. The hard parts are atomicity (if
any sub-step fails we restore the working tree so we don't leave half
a project on disk) and rendering frozen templates instead of shelling
out to `npm create vite` / `uv init` (those outputs aren't
byte-stable across versions, defeating the determinism premise).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Literal

from helixcli import git, templating
from helixcli.errors import AlreadyInitialised, GeneratorFailed, PnpmMissing
from helixcli.manifest import Manifest, StackChoice


def run(
    *,
    project_root: Path,
    name: str,
    frontend: bool,
    backend: bool,
    db: Literal["postgres", "sqlite"],
    force: bool,
) -> dict:
    project_root = project_root.resolve()
    project_root.mkdir(parents=True, exist_ok=True)

    if Manifest.exists(project_root) and not force:
        raise AlreadyInitialised(str(project_root / ".helix" / "manifest.json"))

    # Frontend pkgmgr precondition. We use npm rather than pnpm —
    # pnpm 10's lifecycle-script policy made `pnpm install` exit 1
    # on a vanilla scaffold (esbuild's postinstall flagged ignored
    # despite being whitelisted in both package.json and
    # pnpm-workspace.yaml). npm just works.
    if frontend and not shutil.which("npm"):
        raise PnpmMissing()  # reuses the typed-error label; message updated.

    git_was_fresh = git.init_if_needed(project_root)
    created: list[str] = []

    try:
        if frontend:
            created += _scaffold_frontend(project_root, project_name=name)
        if backend:
            created += _scaffold_backend(project_root, project_name=name, db=db)

        # Cross-cutting: monorepo root files.
        if frontend and backend:
            created += _scaffold_monorepo_root(project_root, project_name=name)
        else:
            # Single-app: no workspace root needed; still drop README +
            # .gitignore so subsequent commits make sense.
            created += _scaffold_root_minimal(project_root, project_name=name)

        manifest = Manifest(
            stack=StackChoice(
                frontend="vite-react-ts" if frontend else None,
                backend="uv-fastapi" if backend else None,
                database=db if backend else None,
            )
        )
        manifest.save(project_root)
        created.append(".helix/manifest.json")
        _write_helix_readme(project_root, manifest)
        created.append(".helix/README.md")

        sha = git.commit_all(project_root, "helixcli init")
    except Exception as e:
        # Atomic failure path: roll back filesystem changes via git so
        # the user (or the agent retrying) sees a clean directory
        # rather than a half-scaffolded mess.
        if git_was_fresh:
            # No prior history to reset to — wipe what we touched.
            for rel in reversed(created):
                p = project_root / rel
                if p.is_file():
                    p.unlink(missing_ok=True)
            shutil.rmtree(project_root / ".git", ignore_errors=True)
        else:
            try:
                git.reset_hard(project_root)
            except subprocess.CalledProcessError:
                pass  # nothing to reset on a fresh init
        if isinstance(e, GeneratorFailed):
            raise
        raise GeneratorFailed("init", str(e)) from e

    return {
        "command": "init",
        "created": created,
        "manifest": manifest.model_dump(mode="json"),
        "git_sha": sha,
    }


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


def _scaffold_frontend(project_root: Path, *, project_name: str) -> list[str]:
    web = project_root / "apps" / "web"
    written: list[str] = []
    ctx = {"project_name": project_name}

    files = [
        ("web/package.json.j2", "package.json"),
        ("web/tsconfig.json.j2", "tsconfig.json"),
        ("web/tsconfig.node.json.j2", "tsconfig.node.json"),
        ("web/vite.config.ts.j2", "vite.config.ts"),
        # Vitest config is split out so vite.config.ts can use vite's
        # `defineConfig` (clean Plugin types) without fighting vitest's
        # version-drifting Plugin types.
        ("web/vitest.config.ts.j2", "vitest.config.ts"),
        ("web/eslint.config.js.j2", "eslint.config.js"),
        ("web/index.html.j2", "index.html"),
        ("web/.gitignore.j2", ".gitignore"),
        ("web/src/main.tsx.j2", "src/main.tsx"),
        ("web/src/App.tsx.j2", "src/App.tsx"),
        ("web/src/index.css.j2", "src/index.css"),
        # Vitest setup file — registers jest-dom matchers. Not a sample
        # test (decision §8.3), just config that has to exist for
        # tests-the-agent-writes-later to pass.
        ("web/src/test-setup.ts.j2", "src/test-setup.ts"),
    ]
    for tpl, dest in files:
        templating.render_to(tpl, web / dest, ctx)
        written.append(str(Path("apps/web") / dest))

    # The inspector script is dev-only and verbatim from the
    # react-vite-typescript skill. Static file because it has no
    # template knobs.
    templating.copy_static(
        "web/src/helix-inspector.ts", web / "src" / "helix-inspector.ts",
    )
    written.append("apps/web/src/helix-inspector.ts")

    return written


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


def _scaffold_backend(
    project_root: Path, *, project_name: str, db: Literal["postgres", "sqlite"],
) -> list[str]:
    api = project_root / "apps" / "api"
    written: list[str] = []
    ctx = {
        "project_name": project_name,
        "db": db,
        "db_dep": "asyncpg" if db == "postgres" else "aiosqlite",
        "default_db_url": (
            "postgresql+asyncpg://helix:helix@localhost:5432/app"
            if db == "postgres"
            else "sqlite+aiosqlite:///./app.db"
        ),
    }

    files = [
        ("api/pyproject.toml.j2", "pyproject.toml"),
        ("api/.python-version.j2", ".python-version"),
        ("api/.gitignore.j2", ".gitignore"),
        ("api/.env.example.j2", ".env.example"),
        ("api/alembic.ini.j2", "alembic.ini"),
        ("api/migrations/env.py.j2", "migrations/env.py"),
        ("api/migrations/script.py.mako.j2", "migrations/script.py.mako"),
        ("api/app/__init__.py.j2", "app/__init__.py"),
        ("api/app/main.py.j2", "app/main.py"),
        ("api/app/api/__init__.py.j2", "app/api/__init__.py"),
        ("api/app/api/health.py.j2", "app/api/health.py"),
        ("api/app/core/__init__.py.j2", "app/core/__init__.py"),
        ("api/app/core/config.py.j2", "app/core/config.py"),
        ("api/app/core/db.py.j2", "app/core/db.py"),
        ("api/app/models/__init__.py.j2", "app/models/__init__.py"),
        ("api/app/models/base.py.j2", "app/models/base.py"),
        ("api/app/schemas/__init__.py.j2", "app/schemas/__init__.py"),
        ("api/app/services/__init__.py.j2", "app/services/__init__.py"),
        ("api/tests/__init__.py.j2", "tests/__init__.py"),
        ("api/tests/conftest.py.j2", "tests/conftest.py"),
    ]
    for tpl, dest in files:
        templating.render_to(tpl, api / dest, ctx)
        written.append(str(Path("apps/api") / dest))

    return written


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


def _scaffold_monorepo_root(project_root: Path, *, project_name: str) -> list[str]:
    written: list[str] = []
    ctx = {"project_name": project_name}
    for tpl, dest in [
        # Root package.json sets up an npm workspace covering apps/web.
        ("root/package.json.j2", "package.json"),
        ("root/README.md.j2", "README.md"),
        ("root/.gitignore.j2", ".gitignore"),
    ]:
        templating.render_to(tpl, project_root / dest, ctx)
        written.append(dest)
    return written


def _scaffold_root_minimal(project_root: Path, *, project_name: str) -> list[str]:
    written: list[str] = []
    ctx = {"project_name": project_name}
    for tpl, dest in [
        ("root/README.md.j2", "README.md"),
        ("root/.gitignore.j2", ".gitignore"),
    ]:
        templating.render_to(tpl, project_root / dest, ctx)
        written.append(dest)
    return written


def _write_helix_readme(project_root: Path, manifest: Manifest) -> None:
    body = templating.render_string(
        "helix/README.md.j2",
        {"manifest": manifest.model_dump(mode="json")},
    )
    (project_root / ".helix" / "README.md").write_text(body, "utf-8")
