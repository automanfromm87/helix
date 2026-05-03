"""`helixcli up` and `helixcli down` — process supervision for the dev
servers, host-side.

In the production helix sandbox, supervisord owns the dev servers and
helixcli should not start them. These commands target host-side
testing where you want one keystroke to bring both up.

Process model:
  * `up` spawns each dev server detached (new session, so killing the
    helixcli process or closing the terminal doesn't take them down).
  * PIDs land in `.helix/pids/<app>.pid`. Logs land in
    `.helix/logs/<app>.log`.
  * `up` is idempotent — if a recorded PID is still alive, we leave it
    alone and report it as already-running.
  * `down` reads the PID files and SIGTERMs (then SIGKILLs after a
    short grace) anything still alive. Cleans up the pid files.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from helixcli.errors import GeneratorFailed, NoManifest, PnpmMissing
from helixcli.manifest import Manifest


_APP_SPECS: dict[str, dict] = {
    "web": {
        # `npm run` resolves the script via the root workspace; we
        # invoke from project root so the `--workspace` flag picks up
        # apps/web's `dev` script.
        "cwd": (),
        "cmd": ["npm", "run", "dev", "--workspace", "apps/web"],
        "url": "http://localhost:5173",
        "needs": "frontend",
        "tool": "npm",
    },
    "api": {
        "cwd": ("apps", "api"),
        "cmd": ["uv", "run", "fastapi", "dev", "app/main.py", "--host", "0.0.0.0", "--port", "8000"],
        "url": "http://localhost:8000",
        "needs": "backend",
        "tool": "uv",
    },
}


def run_up(*, project_root: Path) -> dict:
    project_root = project_root.resolve()
    if not Manifest.exists(project_root):
        raise NoManifest(str(project_root))
    manifest = Manifest.load(project_root)

    started: list[dict] = []
    for app, spec in _APP_SPECS.items():
        if getattr(manifest.stack, spec["needs"]) is None:
            continue
        started.append(_start_one(project_root, app, spec))

    return {"command": "up", "started": started}


def _start_one(project_root: Path, app: str, spec: dict) -> dict:
    pid_path = _pid_path(project_root, app)
    log_path = _log_path(project_root, app)

    existing = _alive_pid(pid_path)
    if existing is not None:
        return {
            "app": app, "pid": existing, "url": spec["url"],
            "log": str(log_path), "status": "already-running",
        }

    if not shutil.which(spec["tool"]):
        if spec["tool"] == "npm":
            raise PnpmMissing()
        raise GeneratorFailed(
            f"up({app})",
            f"{spec['tool']} is not on $PATH",
        )

    cwd = project_root.joinpath(*spec["cwd"])
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log_fh = log_path.open("ab")
    # `start_new_session=True` puts the child in its own process group so
    # closing the parent terminal (or the helixcli process exiting)
    # doesn't take it down. stdin closed so it can never block on input.
    proc = subprocess.Popen(
        spec["cmd"],
        cwd=str(cwd),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ},
    )
    pid_path.write_text(str(proc.pid))

    return {
        "app": app, "pid": proc.pid, "url": spec["url"],
        "log": str(log_path), "status": "started",
    }


def run_down(*, project_root: Path) -> dict:
    project_root = project_root.resolve()
    if not Manifest.exists(project_root):
        raise NoManifest(str(project_root))

    stopped: list[dict] = []
    for app in _APP_SPECS:
        pid_path = _pid_path(project_root, app)
        pid = _alive_pid(pid_path)
        if pid is None:
            if pid_path.exists():
                pid_path.unlink()
                stopped.append({"app": app, "status": "stale-pid-cleaned"})
            else:
                stopped.append({"app": app, "status": "not-running"})
            continue
        _terminate(pid)
        pid_path.unlink(missing_ok=True)
        stopped.append({"app": app, "pid": pid, "status": "stopped"})

    return {"command": "down", "stopped": stopped}


def _terminate(pid: int) -> None:
    """SIGTERM, wait briefly, SIGKILL if still alive. We target the
    process *group* so child processes (e.g. node spawned by npm)
    also exit instead of orphaning."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _is_alive(pid):
            return
        time.sleep(0.1)

    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _pid_path(project_root: Path, app: str) -> Path:
    return project_root / ".helix" / "pids" / f"{app}.pid"


def _log_path(project_root: Path, app: str) -> Path:
    return project_root / ".helix" / "logs" / f"{app}.log"


def _alive_pid(pid_path: Path) -> int | None:
    """Return the PID if the file exists AND the process is alive,
    else None. Cleans up the pid file if the process is dead."""
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        pid_path.unlink(missing_ok=True)
        return None
    if not _is_alive(pid):
        pid_path.unlink(missing_ok=True)
        return None
    return pid


def _is_alive(pid: int) -> bool:
    """`kill -0` style check. PermissionError means the process exists
    but isn't ours — counts as alive for our purposes (we're not the
    only thing on the system that might own a stray pid)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
