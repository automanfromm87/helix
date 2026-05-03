"""`helixcli page <Name>` — emit a frontend page.

Adds three things and updates the manifest:
  apps/web/src/pages/<Name>.tsx           the component
  apps/web/src/pages/<Name>.test.tsx      a smoke test
  apps/web/src/App.tsx                    a `<Route>` for it (best effort)

The router wiring is best-effort: if `App.tsx` already has a
`react-router` setup we splice into it; otherwise we report
`route_wired=false` rather than mangling user code.
"""
from __future__ import annotations

import re
from pathlib import Path

from helixcli import git, templating
from helixcli.errors import GeneratorFailed, NoManifest, StackMismatch
from helixcli.manifest import Manifest, RouteEntry


_PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]+$")


def run(*, project_root: Path, name: str) -> dict:
    project_root = project_root.resolve()
    if not _PASCAL.match(name):
        raise GeneratorFailed("page", f"name {name!r} must be PascalCase")

    if not Manifest.exists(project_root):
        raise NoManifest(str(project_root))
    manifest = Manifest.load(project_root)
    if manifest.stack.frontend is None:
        raise StackMismatch(
            "Project was initialised --backend-only; can't add a page."
        )

    web = project_root / "apps" / "web"
    page_tsx = web / "src" / "pages" / f"{name}.tsx"
    page_test = web / "src" / "pages" / f"{name}.test.tsx"
    if page_tsx.exists() or page_test.exists():
        raise GeneratorFailed("page", f"{name} already exists under apps/web/src/pages/")

    slug = _slugify(name)
    ctx = {"name": name, "slug": slug}

    created: list[str] = []
    try:
        templating.render_to("web/src/pages/_page.tsx.j2", page_tsx, ctx)
        created.append(str(page_tsx.relative_to(project_root)))
        templating.render_to("web/src/pages/_page.test.tsx.j2", page_test, ctx)
        created.append(str(page_test.relative_to(project_root)))

        # Try to wire the route into App.tsx. Fall back to a clear flag
        # in the JSON output if we can't pattern-match the router.
        wired = _wire_route(project_root, name=name, slug=slug)

        manifest.routes.append(
            RouteEntry(
                path=f"/{slug}",
                component=str(page_tsx.relative_to(project_root)),
                test=str(page_test.relative_to(project_root)),
            )
        )
        manifest.save(project_root)

        sha = git.commit_all(project_root, f"helixcli page {name}")
    except Exception as e:
        try:
            git.reset_hard(project_root)
        except Exception:
            pass
        if isinstance(e, GeneratorFailed):
            raise
        raise GeneratorFailed("page", str(e)) from e

    return {
        "command": "page",
        "name": name,
        "created": created,
        "route_path": f"/{slug}",
        "route_wired": wired,
        "git_sha": sha,
    }


def _slugify(name: str) -> str:
    """`Login` → `login`, `UserSettings` → `user-settings`."""
    return re.sub(r"(?<!^)([A-Z])", r"-\1", name).lower()


def _wire_route(project_root: Path, *, name: str, slug: str) -> bool:
    """Splice a `<Route path="/<slug>" element={<Name />} />` into
    `App.tsx`'s `<Routes>` block. Returns True if we managed it; False
    if the file shape didn't match.

    For v0.1 we keep this conservative — if the router isn't already
    set up we don't try to install react-router and rewrite App.tsx in
    one shot. Too easy to mangle.
    """
    app_tsx = project_root / "apps" / "web" / "src" / "App.tsx"
    if not app_tsx.exists():
        return False
    src = app_tsx.read_text("utf-8")
    if f'path="/{slug}"' in src:
        return True  # idempotent

    routes_match = re.search(r"<Routes>(.*?)</Routes>", src, flags=re.DOTALL)
    if routes_match is None:
        return False

    inner = routes_match.group(1).rstrip()
    new_route = f'\n        <Route path="/{slug}" element={{<{name} />}} />'
    new_inner = inner + new_route + "\n      "
    new_src = src.replace(routes_match.group(0), f"<Routes>{new_inner}</Routes>")

    if f"import {name}" not in new_src:
        new_src = re.sub(
            r"(import .* from '[^']+'\n)+",
            lambda m: m.group(0) + f"import {name} from './pages/{name}'\n",
            new_src,
            count=1,
        )

    app_tsx.write_text(new_src, "utf-8")
    return True
