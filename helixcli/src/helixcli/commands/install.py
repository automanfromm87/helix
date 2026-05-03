"""`helixcli install` — install deps for both apps.

`npm install` at the workspace root (covers apps/web via the
`workspaces` field in the root package.json) and `uv sync` in
apps/api, gated on which apps the manifest says exist. Saves the
agent from remembering two cwd + two pkgmgr incantations.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from helixcli.errors import GeneratorFailed, NoManifest, PnpmMissing
from helixcli.manifest import Manifest


def run(*, project_root: Path) -> dict:
    project_root = project_root.resolve()
    if not Manifest.exists(project_root):
        raise NoManifest(str(project_root))
    manifest = Manifest.load(project_root)

    results: list[dict] = []

    if manifest.stack.frontend is not None:
        if not shutil.which("npm"):
            raise PnpmMissing()
        # Run from the workspace root so npm hoists + dedups across
        # root + apps/web. Running inside apps/web would bypass the
        # workspace and create a per-package node_modules.
        results.append(_run_step(
            label="web",
            cmd=["npm", "install"],
            cwd=project_root,
        ))

    if manifest.stack.backend is not None:
        if not shutil.which("uv"):
            raise GeneratorFailed(
                "install",
                "uv is not on $PATH (sandbox image must ship uv)",
            )
        results.append(_run_step(
            label="api",
            cmd=["uv", "sync"],
            cwd=project_root / "apps" / "api",
        ))

    return {"command": "install", "steps": results}


def _run_step(*, label: str, cmd: list[str], cwd: Path) -> dict:
    """Run a sync install command. Streams stdout/stderr through to the
    user's terminal — install logs are long and useful, and the agent
    can still parse the final JSON line."""
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        raise GeneratorFailed(
            f"install({label})",
            f"`{' '.join(cmd)}` exited {proc.returncode} in {cwd}",
        )
    return {"app": label, "cmd": cmd, "cwd": str(cwd), "exit_code": 0}
