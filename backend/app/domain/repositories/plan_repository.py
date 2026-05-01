from typing import List, Optional, Protocol

from app.domain.models.plan import Plan, PlanStatus, Task, TaskInput, TaskStatus


class PlanRepository(Protocol):
    """Plans + Tasks persistence. One repo because Plan is the aggregate root —
    Tasks aren't independently meaningful without their plan."""

    async def create_with_tasks(
        self,
        session_id: str,
        title: str,
        goal: str,
        language: Optional[str],
        tasks: List[TaskInput],
    ) -> Plan:
        """Create a plan and its tasks atomically. Returns the populated Plan."""
        ...

    async def find_plan(self, plan_id: str) -> Optional[Plan]: ...

    async def find_current_plan(self, session_id: str) -> Optional[Plan]:
        """The most recent plan for a session — what the sidebar shows."""
        ...

    async def list_plans(self, session_id: str) -> List[Plan]:
        """All plans for a session, newest first."""
        ...

    async def update_plan_status(
        self, plan_id: str, status: PlanStatus, error: Optional[str] = None
    ) -> None: ...

    async def find_task(self, task_id: str) -> Optional[Task]: ...

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None: ...

    async def increment_task_retries(self, task_id: str) -> int:
        """Atomic +1; returns the new value."""
        ...

    async def block_remaining_tasks(self, plan_id: str, after_position: int) -> int:
        """Mark every task with position > after_position as BLOCKED (with the
        given reason). Used after a hard task failure cascades."""
        ...

    async def unblock_remaining_tasks(self, plan_id: str, after_position: int) -> int:
        """Flip BLOCKED tasks (position > after_position) back to PENDING.
        Used by SKIP / SPLIT recovery to revive the rest of the plan."""
        ...

    async def replace_pending_tasks(
        self, plan_id: str, after_position: int, tasks: List[TaskInput]
    ) -> List[Task]:
        """Replace every PENDING/BLOCKED task with position > after_position by
        a fresh ordered list. Used by the recovery path when the planner
        decides to rewrite the remainder of the plan after a failure.
        Returns the new tasks in position order."""
        ...

    async def insert_tasks_after(
        self, plan_id: str, after_position: int, tasks: List[TaskInput]
    ) -> List[Task]:
        """Insert new tasks immediately after `after_position`, shifting any
        existing PENDING/BLOCKED tasks at later positions to make room.
        Used by the SPLIT recovery decision: replace ONE failed task with
        smaller sub-tasks while keeping the remaining tasks intact.

        Returns the inserted tasks in position order. Completed/failed
        tasks are not touched (they're history)."""
        ...

    async def increment_plan_recovery_count(self, plan_id: str) -> int:
        """Atomic +1 on the plan's recovery counter; returns the new value.
        Used by the flow to cap how many recover-replan cycles one plan can
        run before we force abandonment."""
        ...

    async def reset_running_tasks(self, plan_id: str) -> int:
        """Flip every RUNNING task on the plan back to PENDING. Called by the
        startup reaper: a backend crash leaves the in-flight task stranded in
        RUNNING, but `Plan.next_pending()` only walks PENDING — without this
        reset the resume path silently skips the unfinished task. Returns
        rows touched."""
        ...
