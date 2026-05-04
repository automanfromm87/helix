"""`helixcli component <Name>` — emit a frontend React component.

Adds two files:
  apps/web/src/components/<Name>.tsx
  apps/web/src/components/<Name>.test.tsx

No router wiring (use `helixcli page` for a routed page). The
component is a presentational shell — typed Props, default export,
Tailwind starter — for the agent to flesh out without re-paying the
"how do I structure a component" turn every time.
"""
from __future__ import annotations

import re
from pathlib import Path

from helixcli import git, templating
from helixcli.errors import GeneratorFailed, NoManifest, StackMismatch
from helixcli.manifest import Manifest


_PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]+$")


def run(*, project_root: Path, name: str) -> dict:
    project_root = project_root.resolve()
    if not _PASCAL.match(name):
        raise GeneratorFailed(
            "component", f"name {name!r} must be PascalCase"
        )

    if not Manifest.exists(project_root):
        raise NoManifest(str(project_root))
    manifest = Manifest.load(project_root)
    if manifest.stack.frontend is None:
        raise StackMismatch(
            "Project was initialised --backend-only; can't add a component."
        )

    web = project_root / "apps" / "web"
    component_tsx = web / "src" / "components" / f"{name}.tsx"
    component_test = web / "src" / "components" / f"{name}.test.tsx"
    if component_tsx.exists() or component_test.exists():
        raise GeneratorFailed(
            "component",
            f"{name} already exists under apps/web/src/components/",
        )

    ctx = {"name": name}

    created: list[str] = []
    try:
        templating.render_to(
            "web/src/components/_component.tsx.j2", component_tsx, ctx,
        )
        created.append(str(component_tsx.relative_to(project_root)))
        templating.render_to(
            "web/src/components/_component.test.tsx.j2", component_test, ctx,
        )
        created.append(str(component_test.relative_to(project_root)))

        sha = git.commit_all(project_root, f"helixcli component {name}")
    except Exception as e:
        try:
            git.reset_hard(project_root)
        except Exception:
            pass
        if isinstance(e, GeneratorFailed):
            raise
        raise GeneratorFailed("component", str(e)) from e

    return {
        "command": "component",
        "name": name,
        "created": created,
        "git_sha": sha,
    }
