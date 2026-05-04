"""`helixcli model <Name>` — emit a SQLAlchemy ORM model.

Adds:
  apps/api/app/models/<resource>.py    the ORM class with `Mapped[]` cols
  apps/api/app/models/__init__.py      append the import (re-write file)

`<Name>` is PascalCase (`User`, `Post`, `OrderLine`); the file path is
the snake_case form (`user.py`, `post.py`, `order_line.py`); the
table name is also snake_case but pluralised by appending `s` —
that's the project's convention. Override by editing the model after
generation if a different table name is required.
"""
from __future__ import annotations

import re
from pathlib import Path

from helixcli import git, templating
from helixcli.errors import GeneratorFailed, NoManifest, StackMismatch
from helixcli.manifest import Manifest, ModelEntry


_PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]+$")


def run(*, project_root: Path, name: str) -> dict:
    project_root = project_root.resolve()
    if not _PASCAL.match(name):
        raise GeneratorFailed(
            "model", f"name {name!r} must be PascalCase",
        )

    if not Manifest.exists(project_root):
        raise NoManifest(str(project_root))
    manifest = Manifest.load(project_root)
    if manifest.stack.backend is None:
        raise StackMismatch(
            "Project was initialised --frontend-only; can't add a model."
        )

    file_stem = _snake_case(name)
    table_name = file_stem + "s"  # plural — `user` → `users`, `post` → `posts`

    api = project_root / "apps" / "api"
    model_py = api / "app" / "models" / f"{file_stem}.py"
    init_py = api / "app" / "models" / "__init__.py"
    if model_py.exists():
        raise GeneratorFailed(
            "model", f"{file_stem}.py already exists under apps/api/app/models/",
        )
    if not init_py.exists():
        raise GeneratorFailed(
            "model",
            "apps/api/app/models/__init__.py is missing — re-init the project",
        )

    ctx = {
        "class_name": name,
        "file_stem": file_stem,
        "table_name": table_name,
    }

    created: list[str] = []
    try:
        templating.render_to(
            "api/app/models/_model.py.j2", model_py, ctx,
        )
        created.append(str(model_py.relative_to(project_root)))

        # Append the import to models/__init__.py so Alembic's
        # autogenerate sees it. We rewrite the file rather than
        # patching in place — small file, readability over
        # cleverness.
        _append_to_models_init(init_py, file_stem=file_stem, class_name=name)

        manifest.models.append(
            ModelEntry(
                name=name,
                table=table_name,
                file=str(model_py.relative_to(project_root)),
            )
        )
        manifest.save(project_root)

        sha = git.commit_all(project_root, f"helixcli model {name}")
    except Exception as e:
        try:
            git.reset_hard(project_root)
        except Exception:
            pass
        if isinstance(e, GeneratorFailed):
            raise
        raise GeneratorFailed("model", str(e)) from e

    return {
        "command": "model",
        "name": name,
        "table": table_name,
        "file": str(model_py.relative_to(project_root)),
        "created": created,
        "git_sha": sha,
    }


def _snake_case(pascal: str) -> str:
    """`User` → `user`, `OrderLine` → `order_line`."""
    return re.sub(r"(?<!^)([A-Z])", r"_\1", pascal).lower()


def _append_to_models_init(
    init_py: Path, *, file_stem: str, class_name: str,
) -> None:
    """Splice `from .<file_stem> import <class_name>` into models/__init__.py
    AND extend `__all__` to include the class. Idempotent — re-running for
    the same class is a no-op."""
    src = init_py.read_text(encoding="utf-8")
    import_line = f"from .{file_stem} import {class_name}"
    if import_line in src:
        return  # already present

    # Insert the import after the last existing `from .` import. If
    # none exists yet (just the Base import), that one IS the last.
    lines = src.splitlines(keepends=True)
    last_import_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("from .") or line.startswith("import "):
            last_import_idx = i
    if last_import_idx == -1:
        # No imports at all — prepend.
        lines.insert(0, import_line + "\n")
    else:
        lines.insert(last_import_idx + 1, import_line + "\n")

    new_src = "".join(lines)

    # Extend `__all__` if present. Otherwise leave it alone.
    new_src = re.sub(
        r"__all__\s*=\s*\[([^\]]*)\]",
        lambda m: _extend_all(m.group(1), class_name),
        new_src,
        count=1,
    )
    init_py.write_text(new_src, encoding="utf-8")


def _extend_all(existing: str, class_name: str) -> str:
    quoted = f'"{class_name}"'
    if quoted in existing or f"'{class_name}'" in existing:
        return f"__all__ = [{existing}]"
    stripped = existing.strip().rstrip(",")
    new = stripped + (", " if stripped else "") + quoted
    return f"__all__ = [{new}]"
