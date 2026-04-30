"""Postgres-backed implementation of `SkillStore`.

Stores per-project overrides plus optional global overrides (project_id
NULL). Rows are converted to/from the `Skill` domain model 1:1 — the row's
`id` is internal-only since the domain layer keys skills by `name` within
a (nullable) project scope.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models.skill import Skill
from app.domain.repositories.skill_repository import SkillStore
from app.infrastructure.models.sql import SkillRow


def _row_to_domain(row: SkillRow) -> Skill:
    return Skill(
        name=row.name,
        description=row.description,
        body=row.body,
        source_path=f"db:{row.project_id or 'global'}/{row.name}",
    )


def _scope_filter(project_id: Optional[str]):
    """NULL-aware project scope predicate.

    `IS NULL` and `=` aren't interchangeable for nullable columns in SQL;
    pick the right one based on the runtime value so global overrides
    (project_id=None) match correctly.
    """
    if project_id is None:
        return SkillRow.project_id.is_(None)
    return SkillRow.project_id == project_id


class SqlSkillRepository(SkillStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_for_project(self, project_id: Optional[str]) -> List[Skill]:
        async with self._session_factory() as db:
            stmt = (
                select(SkillRow)
                .where(_scope_filter(project_id))
                .order_by(SkillRow.name)
            )
            rows = (await db.scalars(stmt)).all()
            return [_row_to_domain(r) for r in rows]

    async def get_for_project(
        self, project_id: Optional[str], name: str
    ) -> Optional[Skill]:
        async with self._session_factory() as db:
            stmt = select(SkillRow).where(
                _scope_filter(project_id), SkillRow.name == name
            )
            row = await db.scalar(stmt)
            return _row_to_domain(row) if row else None

    async def upsert(
        self,
        *,
        project_id: Optional[str],
        name: str,
        description: str,
        body: str,
    ) -> Skill:
        # Postgres unique constraints treat NULL as distinct, so a global
        # override (project_id=NULL) wouldn't collide via ON CONFLICT — we do
        # SELECT-then-update-or-insert to handle both scopes uniformly.
        async with self._session_factory() as db:
            existing = await db.scalar(
                select(SkillRow).where(
                    _scope_filter(project_id), SkillRow.name == name
                )
            )
            if existing:
                existing.description = description
                existing.body = body
                row = existing
            else:
                row = SkillRow(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    name=name,
                    description=description,
                    body=body,
                )
                db.add(row)
            await db.commit()
            await db.refresh(row)
            return _row_to_domain(row)

    async def delete(self, *, project_id: Optional[str], name: str) -> bool:
        async with self._session_factory() as db:
            stmt = select(SkillRow).where(
                _scope_filter(project_id), SkillRow.name == name
            )
            row = await db.scalar(stmt)
            if not row:
                return False
            await db.delete(row)
            await db.commit()
            return True
