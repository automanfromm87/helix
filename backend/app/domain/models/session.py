from pydantic import BaseModel, Field
from datetime import datetime, UTC
from typing import List, Optional
from enum import Enum
import uuid
from app.domain.models.event import AgentEvent
from app.domain.models.file import FileInfo


class ContextFile(BaseModel):
    """A user-attached reference document for a session — Markdown notes,
    specs, API docs. Surfaced into the agent's `extra_system_prompt` so
    it's available on every turn without burning a tool call.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    filename: str
    content: str
    size: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionStatus(str, Enum):
    """Session status enum"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    # Task runner died on an unexpected exception (code bug, transient
    # infrastructure error, hot-reload mid-flight). Distinct from COMPLETED
    # so the startup recovery path can pick the session up automatically
    # once the underlying issue is fixed.
    INTERRUPTED = "interrupted"


class SessionSummary(BaseModel):
    """Lightweight session model for list views (excludes heavy events/files)"""
    id: str
    user_id: str
    project_id: Optional[str] = None
    title: Optional[str] = None
    unread_message_count: int = 0
    latest_message: Optional[str] = None
    latest_message_at: Optional[datetime] = None
    status: SessionStatus = SessionStatus.PENDING
    is_shared: bool = False


class Session(BaseModel):
    """Session model"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: str  # User ID that owns this session
    project_id: Optional[str] = None
    # Snapshot of project.system_prompt at session creation. Frozen so a
    # mid-session prompt change in the parent project doesn't shift the agent
    # behavior for this in-flight chat.
    system_prompt: Optional[str] = None
    # Cached markdown summary of `/home/ubuntu/project/` layout, regenerated
    # before each plan when the workspace contents have changed. Lets the
    # planner reason about real file structure instead of guessing.
    workspace_summary: Optional[str] = None
    sandbox_id: Optional[str] = Field(default=None)  # Identifier for the sandbox environment
    agent_id: str
    task_id: Optional[str] = None
    title: Optional[str] = None
    unread_message_count: int = 0
    latest_message: Optional[str] = None
    latest_message_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    events: List[AgentEvent] = []
    files: List[FileInfo] = []
    status: SessionStatus = SessionStatus.PENDING
    is_shared: bool = False  # Whether this session is shared publicly
    # When True, context_files are reached via the `retrieve` tool only —
    # never dumped into `extra_system_prompt`. Worthwhile when the corpus
    # is large enough that the dump cost dominates the token budget.
    retrieval_only_context: bool = False