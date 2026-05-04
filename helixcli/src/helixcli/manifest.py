"""`.helix/manifest.json` — the authoritative project map.

Every generator reads it on the way in and writes it on the way out.
The agent / Helix backend can read this file directly to seed
workspace_summary, so keep the shape stable and forward-compatible
(unknown keys ignored on read, never dropped on write).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from helixcli import __version__

MANIFEST_DIR = ".helix"
MANIFEST_FILE = "manifest.json"


class StackChoice(BaseModel):
    """Which subset of the canonical stack this project uses."""

    frontend: Optional[Literal["vite-react-ts"]] = None
    backend: Optional[Literal["uv-fastapi"]] = None
    database: Optional[Literal["postgres", "sqlite"]] = None


class RouteEntry(BaseModel):
    path: str
    component: str
    test: str


class EndpointEntry(BaseModel):
    method: str
    path: str
    handler: str
    # `schema_ref` not `schema` — Pydantic v2's BaseModel has a
    # deprecated `schema()` method, and a field with that name warns
    # now and breaks in a future major. JSON key in `manifest.json`
    # is unaffected since we serialize via field name.
    schema_ref: Optional[str] = None
    test: str


class ModelEntry(BaseModel):
    name: str
    table: str
    file: str


class Manifest(BaseModel):
    """Schema is forward-compatible: bumping the CLI version bumps
    `helixcli_version` only; structure changes bump `version`."""

    version: int = 1
    stack: StackChoice = Field(default_factory=StackChoice)
    routes: list[RouteEntry] = Field(default_factory=list)
    endpoints: list[EndpointEntry] = Field(default_factory=list)
    models: list[ModelEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    helixcli_version: str = __version__

    @classmethod
    def load(cls, project_root: Path) -> "Manifest":
        path = project_root / MANIFEST_DIR / MANIFEST_FILE
        if not path.exists():
            raise FileNotFoundError(
                f"No manifest at {path} — run `helixcli init` first."
            )
        return cls.model_validate_json(path.read_text("utf-8"))

    def save(self, project_root: Path) -> Path:
        path = project_root / MANIFEST_DIR / MANIFEST_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        # Stable JSON for diff-friendly commits: indent=2, keys not
        # sorted so routes/endpoints stay in declaration order — easier
        # to scan in PR reviews.
        path.write_text(self.model_dump_json(indent=2) + "\n", "utf-8")
        return path

    @classmethod
    def exists(cls, project_root: Path) -> bool:
        return (project_root / MANIFEST_DIR / MANIFEST_FILE).exists()
