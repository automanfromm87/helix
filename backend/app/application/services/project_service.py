"""Project service — sidebar grouping for sessions."""

import logging
from typing import List, Optional

from app.application.errors.exceptions import NotFoundError
from app.domain.models.file import FileInfo
from app.domain.models.project import Project, ProjectSummary
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(
        self,
        project_repository: ProjectRepository,
        session_repository: Optional[SessionRepository] = None,
    ) -> None:
        self._project_repository = project_repository
        self._session_repository = session_repository

    async def list_projects(self, user_id: str) -> List[ProjectSummary]:
        """List a user's projects.

        On first call (no projects yet), creates a default project and pulls
        any orphaned sessions (project_id IS NULL) into it. Subsequent calls
        are pure reads.
        """
        summaries = await self._project_repository.find_summaries_by_user_id(user_id)
        if summaries:
            return summaries
        # Lazy bootstrap.
        default = Project(user_id=user_id, name="My Project")
        await self._project_repository.save(default)
        moved = await self._project_repository.backfill_null_session_project_id(
            user_id, default.id
        )
        if moved:
            logger.info("Backfilled %d ungrouped sessions into default project %s", moved, default.id)
        return await self._project_repository.find_summaries_by_user_id(user_id)

    async def create_project(
        self,
        user_id: str,
        name: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Project:
        project = Project(
            user_id=user_id,
            name=name or "Untitled Project",
            system_prompt=system_prompt,
        )
        await self._project_repository.save(project)
        logger.info("Created project %s for user %s", project.id, user_id)
        return project

    async def rename_project(self, project_id: str, user_id: str, name: str) -> None:
        await self._project_repository.update_name(project_id, user_id, name)
        # 1:1 model: the sidebar label is `session.title || project.name`,
        # which lets auto-derived session titles ("Build a todo app")
        # win over the generic default project name. But once the user
        # explicitly renames, *they* should win — so push the new label
        # onto the underlying session(s) too. No-op if the project has
        # no sessions yet.
        if self._session_repository is not None:
            pairs = await self._session_repository.find_ids_and_sandbox_by_project_id(
                project_id, user_id,
            )
            for session_id, _sandbox_id in pairs:
                await self._session_repository.update_title(session_id, name)

    async def update_system_prompt(
        self, project_id: str, user_id: str, system_prompt: Optional[str]
    ) -> None:
        await self._project_repository.update_system_prompt(
            project_id, user_id, system_prompt
        )

    async def delete_project(self, project_id: str, user_id: str) -> None:
        # Project owns its session(s) — wipe them first so we don't leave
        # orphan rows after the FK switches to SET NULL.
        if self._session_repository is not None:
            await self._session_repository.delete_by_project_id(project_id, user_id)
        deleted = await self._project_repository.delete(project_id, user_id)
        if not deleted:
            raise NotFoundError("Project not found")

    async def get_default_project_id(self, user_id: str) -> str:
        """Project to drop a brand-new session into when caller didn't pick one."""
        summaries = await self.list_projects(user_id)
        return summaries[0].id

    async def get_system_prompt(
        self, project_id: str, user_id: str
    ) -> Optional[str]:
        """Snapshot fed to a new session at creation time."""
        project = await self._project_repository.find_by_id_and_user_id(project_id, user_id)
        return project.system_prompt if project else None

    async def get_project(self, project_id: str, user_id: str) -> Project:
        project = await self._project_repository.find_by_id_and_user_id(project_id, user_id)
        if not project:
            raise NotFoundError("Project not found")
        return project

    async def add_attachment(
        self, project_id: str, user_id: str, file_info: FileInfo
    ) -> None:
        await self._project_repository.add_attachment(project_id, user_id, file_info)

    async def remove_attachment(
        self, project_id: str, user_id: str, file_id: str
    ) -> None:
        await self._project_repository.remove_attachment(project_id, user_id, file_id)

    async def update_shared_memory(
        self, project_id: str, user_id: str, memory: Optional[str]
    ) -> None:
        await self._project_repository.update_shared_memory(project_id, user_id, memory)
