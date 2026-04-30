"""Skill registry protocols.

Two roles, deliberately split:

* `SkillRepository`  — sync read surface served to the agent loop.
  Used by `SkillToolkit.load_skill` and `render_skill_index` on every turn,
  so it MUST be cheap (in-memory). Implementations: `FileSkillRepository`,
  `LayeredSkillRepository`.

* `SkillStore`       — async CRUD over the SQL-backed override store.
  Used by API endpoints and by `_create_task` to snapshot project-scoped
  skills at task-creation time. Implementation: `SqlSkillRepository`.

The async surface is intentionally not a superset of the sync one — a real
DB-backed store can't honor a sync `get(name)` without blocking the event
loop, and the agent tool path can't `await` cheaply on every turn. So we
build a fresh `LayeredSkillRepository` per task instead.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from app.domain.models.skill import Skill


@runtime_checkable
class SkillRepository(Protocol):
    """Sync read-side registry — what the agent sees."""

    def list(self) -> List[Skill]: ...
    def get(self, name: str) -> Optional[Skill]: ...
    def names(self) -> List[str]: ...


class SkillStore(Protocol):
    """Async CRUD over the persistent override store (Postgres)."""

    async def list_for_project(self, project_id: Optional[str]) -> List[Skill]: ...

    async def get_for_project(
        self, project_id: Optional[str], name: str
    ) -> Optional[Skill]: ...

    async def upsert(
        self,
        *,
        project_id: Optional[str],
        name: str,
        description: str,
        body: str,
    ) -> Skill: ...

    async def delete(self, *, project_id: Optional[str], name: str) -> bool: ...
