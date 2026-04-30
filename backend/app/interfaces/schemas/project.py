from typing import List, Optional

from pydantic import BaseModel

from app.domain.models.session import SessionStatus


class ProjectItem(BaseModel):
    """Sidebar entry — a project with its single chat session denormalized."""
    project_id: str
    name: str
    system_prompt: Optional[str] = None
    # Primary session fields (1:1 model — every project has exactly one).
    session_id: Optional[str] = None
    title: Optional[str] = None
    latest_message: Optional[str] = None
    latest_message_at: Optional[int] = None
    status: Optional[SessionStatus] = None
    unread_message_count: int = 0
    is_shared: bool = False


class ListProjectsResponse(BaseModel):
    projects: List[ProjectItem]


class CreateProjectRequest(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None


class CreateProjectResponse(BaseModel):
    project_id: str
    name: str
    system_prompt: Optional[str] = None
    session_id: str


class UpdateProjectRequest(BaseModel):
    """All fields optional — only the ones provided get updated."""
    name: Optional[str] = None
    system_prompt: Optional[str] = None


class ProjectAttachmentItem(BaseModel):
    file_id: str
    filename: str
    size: Optional[int] = None
    content_type: Optional[str] = None


class ProjectAttachmentsResponse(BaseModel):
    attachments: List[ProjectAttachmentItem]
