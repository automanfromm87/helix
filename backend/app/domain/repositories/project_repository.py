from typing import List, Optional, Protocol

from app.domain.models.file import FileInfo
from app.domain.models.project import Project, ProjectSummary


class ProjectRepository(Protocol):
    async def save(self, project: Project) -> None: ...

    async def find_by_id_and_user_id(
        self, project_id: str, user_id: str
    ) -> Optional[Project]: ...

    async def find_summaries_by_user_id(self, user_id: str) -> List[ProjectSummary]: ...

    async def update_name(self, project_id: str, user_id: str, name: str) -> None: ...

    async def update_system_prompt(
        self, project_id: str, user_id: str, system_prompt: Optional[str]
    ) -> None: ...

    async def delete(self, project_id: str, user_id: str) -> bool: ...

    async def backfill_null_session_project_id(
        self, user_id: str, project_id: str
    ) -> int:
        """Migrate every session of `user_id` with NULL project_id to `project_id`."""
        ...

    async def add_attachment(
        self, project_id: str, user_id: str, file_info: FileInfo
    ) -> None: ...

    async def remove_attachment(
        self, project_id: str, user_id: str, file_id: str
    ) -> None: ...

    async def update_shared_memory(
        self, project_id: str, user_id: str, memory: Optional[str]
    ) -> None: ...
