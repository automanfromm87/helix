"""Jinja2 wrapper. Templates live next to the package source and are
resolved relatively. Works the same for `pip install -e .` checkouts
and wheel installs because we ship the package as plain files (no zip
imports) — see pyproject's hatch.build.targets.wheel.force-include."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _templates_root() -> Path:
    return Path(__file__).resolve().parent / "templates"


_env: Environment | None = None


def env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(_templates_root()),
            undefined=StrictUndefined,  # template typo → loud error
            keep_trailing_newline=True,
        )
    return _env


def render_to(template_path: str, dest: Path, ctx: dict[str, Any]) -> None:
    """Render `template_path` (relative to the templates root) into
    `dest`. Creates parent dirs as needed. Refuses to overwrite an
    existing file — generators shouldn't clobber user code."""
    if dest.exists():
        raise FileExistsError(f"Refusing to overwrite {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = env().get_template(template_path).render(**ctx)
    dest.write_text(out, "utf-8")


def render_string(template_path: str, ctx: dict[str, Any]) -> str:
    """Render to a string without writing — used by patch-style
    generators that need to splice into an existing file."""
    return env().get_template(template_path).render(**ctx)


def copy_static(rel_path: str, dest: Path) -> None:
    """Copy a file from templates verbatim (no Jinja rendering). Used
    for files like `helix-inspector.ts` that are already valid TS and
    just need to be dropped in."""
    src = _templates_root() / rel_path
    if dest.exists():
        raise FileExistsError(f"Refusing to overwrite {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
