"""Plans + Tasks domain models.

Each user message kicks off a new Plan. The Plan owns an ordered list of Tasks
that the agent must complete sequentially before yielding control back. Both
are persisted in Postgres so they survive backend restarts and can be
inspected / edited via API.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, List, Optional
import uuid

from pydantic import BaseModel, Field, model_validator


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    # Set on tasks that follow a failed one — they were never attempted because
    # the prior task is a hard prerequisite.
    BLOCKED = "blocked"


class PlanStatus(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(BaseModel):
    """One unit of agent work.

    `title` is the one-line action shown bold in the plan UI; `details` is
    an optional markdown body shown collapsed by default — list of
    deliverables, acceptance criteria, follow-ups, etc.
    """

    id: str = Field(default_factory=_new_id)
    plan_id: str
    position: int  # 0-indexed; agent works through these in order
    title: str = ""
    details: Optional[str] = None
    # Out-of-scope items the executor MUST NOT pursue. Surfaced as a
    # system reminder during the ReAct loop so the model treats matching
    # tool failures as blockers rather than rabbit holes to fix.
    explicit_non_goals: List[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    retries: int = 0  # number of failed attempts so far (excluding the last attempt)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _backfill_title_from_description(cls, values: Any) -> Any:
        """Old SessionEventRow JSON used `description` only — when we
        re-validate those rows on startup, treat the legacy field as the
        title (and drop it from `details` since it's already the body)."""
        if not isinstance(values, dict):
            return values
        has_title = bool(values.get("title"))
        legacy_desc = values.get("description")
        if not has_title and isinstance(legacy_desc, str) and legacy_desc:
            values["title"] = legacy_desc
        return values

    @property
    def description(self) -> str:
        """Concatenated title + details, used by the executor prompt as the
        single human-readable string. Two spaces between so prompt-side
        markdown rendering keeps title and bullet list visually distinct."""
        if self.details:
            return f"{self.title}\n\n{self.details}"
        return self.title

    def is_done(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED)


class TaskInput(BaseModel):
    """Service-layer DTO for proposing tasks (planner → repository)."""

    title: str
    details: Optional[str] = None
    explicit_non_goals: List[str] = Field(default_factory=list)


class Plan(BaseModel):
    id: str = Field(default_factory=_new_id)
    session_id: str
    title: str = ""
    goal: str = ""
    language: Optional[str] = "en"
    status: PlanStatus = PlanStatus.PLANNING
    error: Optional[str] = None
    tasks: List[Task] = []
    # How many times this plan has gone through the recovery (replan) loop.
    # The flow caps this so a planner that keeps choosing replan can't
    # produce an unbounded series of failed cycles.
    recovery_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: Optional[datetime] = None
    # Auto-set when the plan finishes and `git commit` succeeds against
    # the session's project dir. Used by the FE to show "v3 · abc123" +
    # diff/restore affordances.
    commit_sha: Optional[str] = None

    def next_pending(self) -> Optional[Task]:
        for task in sorted(self.tasks, key=lambda t: t.position):
            if task.status == TaskStatus.PENDING:
                return task
        return None
