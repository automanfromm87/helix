"""`helixcli hook <Name>` — emit a custom React hook.

Adds two files:
  apps/web/src/hooks/use<Name>.ts
  apps/web/src/hooks/use<Name>.test.tsx

`<Name>` is PascalCase (matches React's hook-naming convention —
`useTheme`, `usePosts`, `useDebounce`). The generator prepends `use`
so the agent passes the noun, not the full hook name.

The body is a placeholder `{ value, set }` pair — the agent rewrites
the return shape and signature to match the real domain.
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
            "hook", f"name {name!r} must be PascalCase (without leading 'use')",
        )

    if not Manifest.exists(project_root):
        raise NoManifest(str(project_root))
    manifest = Manifest.load(project_root)
    if manifest.stack.frontend is None:
        raise StackMismatch(
            "Project was initialised --backend-only; can't add a hook."
        )

    web = project_root / "apps" / "web"
    hook_ts = web / "src" / "hooks" / f"use{name}.ts"
    hook_test = web / "src" / "hooks" / f"use{name}.test.tsx"
    if hook_ts.exists() or hook_test.exists():
        raise GeneratorFailed(
            "hook",
            f"use{name} already exists under apps/web/src/hooks/",
        )

    ctx = {"name": name}

    created: list[str] = []
    try:
        templating.render_to("web/src/hooks/_hook.ts.j2", hook_ts, ctx)
        created.append(str(hook_ts.relative_to(project_root)))
        templating.render_to("web/src/hooks/_hook.test.tsx.j2", hook_test, ctx)
        created.append(str(hook_test.relative_to(project_root)))

        sha = git.commit_all(project_root, f"helixcli hook use{name}")
    except Exception as e:
        try:
            git.reset_hard(project_root)
        except Exception:
            pass
        if isinstance(e, GeneratorFailed):
            raise
        raise GeneratorFailed("hook", str(e)) from e

    return {
        "command": "hook",
        "name": f"use{name}",
        "created": created,
        "git_sha": sha,
    }
