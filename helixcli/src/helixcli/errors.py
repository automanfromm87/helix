"""Typed CLI errors.

Each error carries the exit code SPEC.md §4 mandates, so commands can
just `raise HelixCliError(...)` and the entry-point translates
uniformly. Don't catch these inside commands — let them bubble.
"""
from __future__ import annotations


class HelixCliError(Exception):
    exit_code: int = 70  # internal failure (SPEC §4 default)

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AlreadyInitialised(HelixCliError):
    exit_code = 64

    def __init__(self, manifest_path: str) -> None:
        super().__init__(
            f"Project already initialised ({manifest_path} exists). "
            "Pass --force to re-init."
        )


class PnpmMissing(HelixCliError):
    """Historical name — we now check for npm specifically (the project
    moved off pnpm because pnpm 10's lifecycle-script policy fought every
    fresh scaffold). Class name kept for ABI stability; message updated."""

    exit_code = 65

    def __init__(self) -> None:
        super().__init__(
            "npm is not on $PATH. Install Node.js (which ships npm) before "
            "scaffolding the frontend. The sandbox image must include npm."
        )


class NoManifest(HelixCliError):
    exit_code = 66

    def __init__(self, project_root: str) -> None:
        super().__init__(
            f"No .helix/manifest.json under {project_root}. "
            "Run `helixcli init` first."
        )


class StackMismatch(HelixCliError):
    """Generator can't run because the project's stack doesn't include
    the side it targets (e.g. `helixcli page` on a backend-only init)."""

    exit_code = 67

    def __init__(self, message: str) -> None:
        super().__init__(message)


class GeneratorFailed(HelixCliError):
    """Wraps a tool subprocess (npm, uv, alembic) failure. Generators
    catch the underlying CalledProcessError and raise this to add
    context the user actually wants."""

    exit_code = 70

    def __init__(self, what: str, detail: str) -> None:
        super().__init__(f"{what} failed: {detail}")
