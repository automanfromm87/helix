"""`helixcli endpoint <METHOD> <path>` — emit a backend endpoint.

Adds:
  apps/api/app/api/<resource>.py     handler (created or appended to)
  apps/api/app/schemas/<resource>.py request/response Pydantic models
                                     (skipped for GETs with no body)
  apps/api/tests/test_<resource>.py  pytest test
And updates the manifest + auto-commits.

`<resource>` is derived from the path: `/api/v1/auth/login` → `auth`.
For nested paths (`/api/v1/users/{id}/posts`) it falls back to the
first non-versioned segment (`users`) to keep things predictable.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from helixcli import git, templating
from helixcli.errors import GeneratorFailed, NoManifest, StackMismatch
from helixcli.manifest import EndpointEntry, Manifest


def run(
    *,
    project_root: Path,
    method: str,
    path: str,
    auth: Literal["required", "public"],
) -> dict:
    project_root = project_root.resolve()
    if not Manifest.exists(project_root):
        raise NoManifest(str(project_root))
    manifest = Manifest.load(project_root)
    if manifest.stack.backend is None:
        raise StackMismatch(
            "Project was initialised --frontend-only; can't add an endpoint."
        )

    if not path.startswith("/"):
        raise GeneratorFailed("endpoint", f"path {path!r} must start with '/'")

    resource = _resource_from_path(path)
    rel_path = _strip_router_prefix(path)
    handler_name = _handler_name(method, rel_path)
    has_body = method in ("POST", "PUT", "PATCH")

    api = project_root / "apps" / "api"
    handler_file = api / "app" / "api" / f"{resource}.py"
    schema_file = api / "app" / "schemas" / f"{resource}.py"
    test_file = api / "tests" / f"test_{resource}.py"

    ctx = {
        "method": method,
        "method_lower": method.lower(),
        "path": path,
        "rel_path": rel_path,
        "resource": resource,
        "handler_name": handler_name,
        "auth": auth,
        "has_body": has_body,
        "schema_class": _schema_class(handler_name),
    }

    created: list[str] = []
    try:
        # Handler file: create OR append. We append a single new
        # function — never edit existing functions.
        if handler_file.exists():
            _append_handler(handler_file, ctx)
        else:
            templating.render_to("api/app/api/_endpoint.py.j2", handler_file, ctx)
            created.append(str(handler_file.relative_to(project_root)))
            _register_router(project_root, resource)

        # Schema file (only when the method has a body).
        if has_body:
            if schema_file.exists():
                _append_schema(schema_file, ctx)
            else:
                templating.render_to(
                    "api/app/schemas/_endpoint.py.j2", schema_file, ctx,
                )
                created.append(str(schema_file.relative_to(project_root)))

        # Test file: create OR append.
        if test_file.exists():
            _append_test(test_file, ctx)
        else:
            templating.render_to(
                "api/tests/_test_endpoint.py.j2", test_file, ctx,
            )
            created.append(str(test_file.relative_to(project_root)))

        manifest.endpoints.append(
            EndpointEntry(
                method=method,
                path=path,
                handler=f"{handler_file.relative_to(project_root)}:{handler_name}",
                schema_ref=(
                    f"{schema_file.relative_to(project_root)}:{ctx['schema_class']}Request"
                    if has_body
                    else None
                ),
                test=str(test_file.relative_to(project_root)),
            )
        )
        manifest.save(project_root)

        sha = git.commit_all(project_root, f"helixcli endpoint {method} {path}")
    except Exception as e:
        try:
            git.reset_hard(project_root)
        except Exception:
            pass
        if isinstance(e, GeneratorFailed):
            raise
        raise GeneratorFailed("endpoint", str(e)) from e

    return {
        "command": "endpoint",
        "method": method,
        "path": path,
        "created": created,
        "git_sha": sha,
    }


# ---------------------------------------------------------------------------
# Path / name derivation
# ---------------------------------------------------------------------------


def _resource_from_path(path: str) -> str:
    """`/api/v1/auth/login` → `auth`."""
    parts = [p for p in path.strip("/").split("/") if p]
    while parts and (parts[0] == "api" or re.fullmatch(r"v\d+", parts[0])):
        parts.pop(0)
    if not parts:
        raise GeneratorFailed("endpoint", f"can't derive resource from {path!r}")
    return parts[0].replace("-", "_")


def _strip_router_prefix(path: str) -> str:
    """`/api/v1/auth/login` → `/login` (path inside the auth router).

    The router itself is mounted with `prefix="/<resource>"` under
    `/api/v1`, so each handler's `@router.<verb>(...)` only sees the
    tail.
    """
    parts = [p for p in path.strip("/").split("/") if p]
    while parts and (parts[0] == "api" or re.fullmatch(r"v\d+", parts[0])):
        parts.pop(0)
    if parts:
        parts.pop(0)  # drop the resource segment too
    rel = "/" + "/".join(parts) if parts else ""
    return rel or "/"


def _handler_name(method: str, rel_path: str) -> str:
    """`POST /login` → `login_post`, `GET /` → `index`."""
    parts = [p for p in rel_path.strip("/").split("/") if p]
    parts = [re.sub(r"\{([^}]+)\}", r"by_\1", p) for p in parts]
    base = "_".join(parts) or "index"
    return f"{base}_{method.lower()}" if base != "index" else f"{method.lower()}_index"


def _schema_class(handler_name: str) -> str:
    """`login_post` → `LoginPost`."""
    return "".join(part.capitalize() for part in handler_name.split("_"))


# ---------------------------------------------------------------------------
# File mutations (append-style)
# ---------------------------------------------------------------------------


def _append_handler(handler_file: Path, ctx: dict) -> None:
    """Append a new handler function to an existing router file. If the
    new handler has a request body, also extend the
    `from app.schemas.<resource> import ...` line at the top so the
    referenced types resolve — without this the appended handler
    would NameError at import time."""
    src = handler_file.read_text("utf-8")
    if ctx["has_body"]:
        src = _ensure_schema_import(src, ctx)
    snippet = templating.render_string("api/app/api/_endpoint_append.py.j2", ctx)
    handler_file.write_text(src.rstrip() + "\n\n\n" + snippet, encoding="utf-8")


def _ensure_schema_import(src: str, ctx: dict) -> str:
    """Add the new schema names to the existing schema import line.
    Idempotent — a re-run with the same names is a no-op."""
    resource = ctx["resource"]
    schema_class = ctx["schema_class"]
    new_names = {f"{schema_class}Request", f"{schema_class}Response"}
    pattern = re.compile(
        rf"^from app\.schemas\.{re.escape(resource)} import (.+)$",
        flags=re.MULTILINE,
    )
    match = pattern.search(src)
    if match is None:
        # No prior schema import (rare — file exists but every prior
        # handler was a body-less GET). Splice a fresh import after
        # the `fastapi` import block.
        new_line = (
            f"from app.schemas.{resource} import "
            f"{schema_class}Request, {schema_class}Response"
        )
        return re.sub(
            r"^(from fastapi import APIRouter)$",
            rf"\1\n{new_line}",
            src,
            count=1,
            flags=re.MULTILINE,
        )
    existing = {n.strip() for n in match.group(1).split(",")}
    merged = sorted(existing | new_names)
    new_line = f"from app.schemas.{resource} import {', '.join(merged)}"
    return src[: match.start()] + new_line + src[match.end():]


def _append_schema(schema_file: Path, ctx: dict) -> None:
    snippet = templating.render_string("api/app/schemas/_endpoint_append.py.j2", ctx)
    with schema_file.open("a", encoding="utf-8") as f:
        f.write("\n\n" + snippet)


def _append_test(test_file: Path, ctx: dict) -> None:
    snippet = templating.render_string("api/tests/_test_endpoint_append.py.j2", ctx)
    with test_file.open("a", encoding="utf-8") as f:
        f.write("\n\n" + snippet)


def _register_router(project_root: Path, resource: str) -> None:
    """Append a router include to `app/api/__init__.py`."""
    init_file = project_root / "apps" / "api" / "app" / "api" / "__init__.py"
    src = init_file.read_text("utf-8")
    if f"from .{resource}" in src:
        return
    if f"include_router({resource}_router" in src:
        return
    import_line = f"from .{resource} import router as {resource}_router\n"
    include_line = f"api_router.include_router({resource}_router)\n"
    src = src.replace(
        "from .health import router as health_router\n",
        f"from .health import router as health_router\n{import_line}",
        1,
    )
    src = src.replace(
        "api_router.include_router(health_router)\n",
        f"api_router.include_router(health_router)\n{include_line}",
        1,
    )
    init_file.write_text(src, "utf-8")
