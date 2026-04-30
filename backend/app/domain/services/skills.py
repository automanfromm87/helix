"""Layered skill registry.

Composes a base file-based registry (global, committed) with a snapshot of
DB-backed overrides for one project scope. Resolution order, highest wins:

  1. Project-scoped DB skill (`project_id == <this_project>`)
  2. Global DB override        (`project_id IS NULL`)
  3. File-based skill          (`backend/skills/<name>/SKILL.md`)

Built once at task creation by `_create_task` and treated as immutable for
the duration of the task — the agent's tool loop reads it on every turn,
and async DB lookups in that hot path would defeat prompt-cache reuse.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from app.domain.models.skill import Skill
from app.domain.repositories.skill_repository import SkillRepository


class LayeredSkillRepository(SkillRepository):
    """In-memory composite registry — resolved at construction time."""

    def __init__(
        self,
        *,
        base: SkillRepository,
        global_overrides: Optional[Iterable[Skill]] = None,
        project_overrides: Optional[Iterable[Skill]] = None,
    ) -> None:
        merged: dict[str, Skill] = {s.name: s for s in base.list()}
        for skill in global_overrides or ():
            merged[skill.name] = skill
        for skill in project_overrides or ():
            merged[skill.name] = skill
        self._skills: dict[str, Skill] = merged

    def list(self) -> List[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def names(self) -> List[str]:
        return sorted(self._skills)
