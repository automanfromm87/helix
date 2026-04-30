"""Postgres implementation of ProjectRepository."""

import logging
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.errors.exceptions import NotFoundError
from app.domain.models.file import FileInfo
from app.domain.models.project import Project, ProjectSummary
from app.domain.models.session import SessionStatus
from app.domain.repositories.project_repository import ProjectRepository
from app.infrastructure.models.sql import ProjectRow, SessionRow

logger = logging.getLogger(__name__)


def _row_to_domain(row: ProjectRow) -> Project:
    return Project(
        id=row.project_id,
        user_id=row.user_id,
        name=row.name,
        system_prompt=row.system_prompt,
        attachments=[FileInfo.model_validate(a) for a in (row.attachments or [])],
        shared_memory=row.shared_memory,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _domain_to_row(project: Project) -> ProjectRow:
    return ProjectRow(
        project_id=project.id,
        user_id=project.user_id,
        name=project.name,
        system_prompt=project.system_prompt,
        attachments=[a.model_dump(mode="json") for a in project.attachments],
        shared_memory=project.shared_memory,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


class SqlProjectRepository(ProjectRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, project: Project) -> None:
        async with self._session_factory() as db:
            row = await db.get(ProjectRow, project.id)
            if not row:
                db.add(_domain_to_row(project))
            else:
                row.name = project.name
                row.system_prompt = project.system_prompt
                row.attachments = [a.model_dump(mode="json") for a in project.attachments]
                row.shared_memory = project.shared_memory
            await db.commit()

    async def find_by_id_and_user_id(
        self, project_id: str, user_id: str
    ) -> Optional[Project]:
        async with self._session_factory() as db:
            row = await db.scalar(
                select(ProjectRow).where(
                    ProjectRow.project_id == project_id,
                    ProjectRow.user_id == user_id,
                )
            )
            return _row_to_domain(row) if row else None

    async def find_summaries_by_user_id(self, user_id: str) -> List[ProjectSummary]:
        """One ProjectSummary per project, with its primary session denormalized.

        Each project has exactly one session in the 1:1 model. If multiple
        sessions ever exist (legacy data), we pick the most recently active
        one via DISTINCT ON.
        """
        async with self._session_factory() as db:
            # PostgreSQL DISTINCT ON: pick the latest session per project_id.
            primary_session_stmt = (
                select(
                    SessionRow.project_id,
                    SessionRow.session_id,
                    SessionRow.title,
                    SessionRow.latest_message,
                    SessionRow.latest_message_at,
                    SessionRow.unread_message_count,
                    SessionRow.status,
                    SessionRow.is_shared,
                )
                .where(SessionRow.project_id.is_not(None))
                .distinct(SessionRow.project_id)
                .order_by(
                    SessionRow.project_id,
                    SessionRow.latest_message_at.desc().nullslast(),
                    SessionRow.created_at.desc(),
                )
                .subquery()
            )

            stmt = (
                select(ProjectRow, primary_session_stmt)
                .join(
                    primary_session_stmt,
                    primary_session_stmt.c.project_id == ProjectRow.project_id,
                    isouter=True,
                )
                .where(ProjectRow.user_id == user_id)
                .order_by(ProjectRow.created_at.asc())
            )
            result = await db.execute(stmt)
            summaries: List[ProjectSummary] = []
            for row in result.all():
                project = row[0]
                summaries.append(
                    ProjectSummary(
                        id=project.project_id,
                        name=project.name,
                        system_prompt=project.system_prompt,
                        created_at=project.created_at,
                        session_id=row.session_id,
                        title=row.title,
                        latest_message=row.latest_message,
                        latest_message_at=row.latest_message_at,
                        unread_message_count=row.unread_message_count or 0,
                        status=SessionStatus(row.status) if row.status else None,
                        is_shared=bool(row.is_shared) if row.is_shared is not None else False,
                    )
                )
            return summaries

    async def update_name(self, project_id: str, user_id: str, name: str) -> None:
        async with self._session_factory() as db:
            result = await db.execute(
                update(ProjectRow)
                .where(
                    ProjectRow.project_id == project_id,
                    ProjectRow.user_id == user_id,
                )
                .values(name=name)
            )
            if result.rowcount == 0:
                raise NotFoundError(f"Project {project_id} not found")
            await db.commit()

    async def update_system_prompt(
        self, project_id: str, user_id: str, system_prompt: Optional[str]
    ) -> None:
        async with self._session_factory() as db:
            result = await db.execute(
                update(ProjectRow)
                .where(
                    ProjectRow.project_id == project_id,
                    ProjectRow.user_id == user_id,
                )
                .values(system_prompt=system_prompt)
            )
            if result.rowcount == 0:
                raise NotFoundError(f"Project {project_id} not found")
            await db.commit()

    async def delete(self, project_id: str, user_id: str) -> bool:
        async with self._session_factory() as db:
            row = await db.scalar(
                select(ProjectRow).where(
                    ProjectRow.project_id == project_id,
                    ProjectRow.user_id == user_id,
                )
            )
            if not row:
                return False
            # Sessions stay alive; ON DELETE SET NULL handles the FK.
            await db.delete(row)
            await db.commit()
            return True

    async def backfill_null_session_project_id(
        self, user_id: str, project_id: str
    ) -> int:
        async with self._session_factory() as db:
            result = await db.execute(
                update(SessionRow)
                .where(
                    SessionRow.user_id == user_id,
                    SessionRow.project_id.is_(None),
                )
                .values(project_id=project_id)
            )
            await db.commit()
            return result.rowcount or 0

    async def add_attachment(
        self, project_id: str, user_id: str, file_info: FileInfo
    ) -> None:
        async with self._session_factory() as db:
            row = await db.scalar(
                select(ProjectRow).where(
                    ProjectRow.project_id == project_id,
                    ProjectRow.user_id == user_id,
                )
            )
            if not row:
                raise NotFoundError(f"Project {project_id} not found")
            existing = list(row.attachments or [])
            existing.append(file_info.model_dump(mode="json"))
            # Reassign so SQLAlchemy sees the JSONB column as dirty.
            row.attachments = existing
            await db.commit()

    async def remove_attachment(
        self, project_id: str, user_id: str, file_id: str
    ) -> None:
        async with self._session_factory() as db:
            row = await db.scalar(
                select(ProjectRow).where(
                    ProjectRow.project_id == project_id,
                    ProjectRow.user_id == user_id,
                )
            )
            if not row:
                raise NotFoundError(f"Project {project_id} not found")
            row.attachments = [
                a for a in (row.attachments or []) if a.get("file_id") != file_id
            ]
            await db.commit()

    async def update_shared_memory(
        self, project_id: str, user_id: str, memory: Optional[str]
    ) -> None:
        async with self._session_factory() as db:
            result = await db.execute(
                update(ProjectRow)
                .where(
                    ProjectRow.project_id == project_id,
                    ProjectRow.user_id == user_id,
                )
                .values(shared_memory=memory)
            )
            if result.rowcount == 0:
                raise NotFoundError(f"Project {project_id} not found")
            await db.commit()
