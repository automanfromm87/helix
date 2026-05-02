"""SQLAlchemy ORM models.

`session_events` is a dedicated append-only table rather than a JSONB array
on the session row, so emitting one event is a single constant-time INSERT
instead of rewriting the whole row.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fullname: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_users_fullname", "fullname"),)


class AgentRow(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    # Memories are heterogenous Memory objects keyed by name; JSONB keeps the
    # original shape with no extra modeling.
    memories: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class ProjectRow(Base):
    """Sidebar grouping label. No content of its own — just a name + ownership."""

    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="Untitled Project")
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Project-level files (FileInfo dumps). Synced into each session's sandbox.
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # Rolling summary of past sessions — injected into the system prompt of new
    # sessions so the workspace's accumulated context survives across chats.
    shared_memory: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # NULL means the session is "ungrouped" — happens transiently when the
    # owning project is deleted (FK is ON DELETE SET NULL).
    project_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("projects.project_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    workspace_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sandbox_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    unread_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latest_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Files attached to a session — small enough to stay denormalized as JSONB
    # (matches the `Session.files: List[FileInfo]` domain model directly).
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    events: Mapped[list["SessionEventRow"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionEventRow.id",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_sessions_user_latest", "user_id", "latest_message_at"),
    )


class SessionEventRow(Base):
    """Append-only log of agent events. One row per emitted event."""

    __tablename__ = "session_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    session: Mapped[SessionRow] = relationship(back_populates="events")

    __table_args__ = (Index("ix_session_events_session_id_id", "session_id", "id"),)


class LLMCallRow(Base):
    """One row per LLM invocation. Powers usage/error/latency stats."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    # `tokens_in` is the freshly-billed input. Anthropic reports
    # cache_read / cache_creation SEPARATELY; the actual prompt seen by the
    # model is the sum of all three. Cache hit rate is therefore
    # `cache_read / (tokens_in + cache_read + cache_creation)`.
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )


class PlanRow(Base):
    """One Plan per user message — captures goal + ordered task list.

    The session_id FK is ON DELETE CASCADE so deleting a session wipes its
    plans (and tasks via their own cascade) without leaving orphans.
    """

    __tablename__ = "plans"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planning")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Number of replan cycles run on this plan; the flow caps it.
    recovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when the plan completes successfully and the auto-commit lands.
    # NULL for plans that produced no file changes, plans that pre-date
    # the versioning feature, or runs where git unexpectedly errored out.
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    tasks: Mapped[list["TaskRow"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TaskRow.position",
        lazy="selectin",
    )


class TaskRow(Base):
    """One Task = one ReAct unit. Agent loops through these in `position` order."""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("plans.plan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Headline shown bold in the plan UI (≤ ~80 chars).
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # Optional markdown body — deliverables, acceptance criteria, etc.
    # Was the only field before `title` was introduced; legacy rows have
    # the full text here and an empty `title`.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    plan: Mapped[PlanRow] = relationship(back_populates="tasks")


class SkillRow(Base):
    """Project-scoped skill overrides.

    `project_id` NULL means a global override that shadows a same-named
    file-based skill across every project. NOT NULL scopes the skill to one
    project — `LayeredSkillRepository` overlays it on top of the file/global
    layers when serving that project.
    """

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_skills_project_name"),
    )


class FileRow(Base):
    """Binary file storage."""

    __tablename__ = "files"

    file_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Defer the binary blob — `get_file_info` and metadata-only paths shouldn't
    # pull megabytes of content into memory.
    content: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    upload_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
