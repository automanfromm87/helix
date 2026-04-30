from datetime import UTC, datetime
from typing import List, Optional
import uuid

from pydantic import BaseModel, Field

from app.domain.models.file import FileInfo
from app.domain.models.session import SessionStatus


class Project(BaseModel):
    """A 1:1 chat workspace. Each project owns exactly one chat session."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: str
    name: str = "Untitled Project"
    system_prompt: Optional[str] = None
    # Files attached to the project itself — synced into every new session's
    # sandbox at /home/ubuntu/project/.
    attachments: List[FileInfo] = []
    # Rolling summary of past sessions in this project. Injected into new
    # sessions' system prompt so accumulated knowledge carries across chats.
    shared_memory: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectSummary(BaseModel):
    """Sidebar entry — one project, denormalized with its primary session."""

    id: str
    name: str
    system_prompt: Optional[str] = None
    created_at: Optional[datetime] = None

    # The session this project shows in the sidebar. Always present after a
    # project has been created (we ensure one exists at creation time).
    session_id: Optional[str] = None
    title: Optional[str] = None
    latest_message: Optional[str] = None
    latest_message_at: Optional[datetime] = None
    unread_message_count: int = 0
    status: Optional[SessionStatus] = None
    is_shared: bool = False
