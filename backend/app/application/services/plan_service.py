"""Application-layer Plan/Task orchestration."""

import logging
from typing import List, Optional

from app.application.errors.exceptions import NotFoundError
from app.domain.models.plan import Plan, PlanStatus, Task, TaskInput, TaskStatus
from app.domain.repositories.plan_repository import PlanRepository
from app.domain.repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)


class PlanService:
    # Per-task retry budget. After this many failed runs of a task we give up
    # and propagate the failure (BLOCKED cascade to remaining tasks).
    MAX_TASK_RETRIES: int = 1

    def __init__(
        self,
        plan_repository: PlanRepository,
        session_repository: SessionRepository,
    ) -> None:
        self._plans = plan_repository
        self._sessions = session_repository

    async def start_plan(
        self,
        session_id: str,
        title: str,
        goal: str,
        language: Optional[str],
        tasks: List[TaskInput],
    ) -> Plan:
        """Atomic create-and-fan-out: one plan + N tasks in pending state."""
        return await self._plans.create_with_tasks(
            session_id=session_id,
            title=title,
            goal=goal,
            language=language,
            tasks=tasks,
        )

    async def mark_plan_executing(self, plan_id: str) -> None:
        await self._plans.update_plan_status(plan_id, PlanStatus.EXECUTING)

    async def mark_plan_completed(self, plan_id: str) -> None:
        await self._plans.update_plan_status(plan_id, PlanStatus.COMPLETED)

    async def mark_plan_failed(self, plan_id: str, error: str) -> None:
        await self._plans.update_plan_status(plan_id, PlanStatus.FAILED, error=error)

    async def list_plans(
        self, session_id: str, user_id: str
    ) -> List[Plan]:
        await self._verify_session(session_id, user_id)
        return await self._plans.list_plans(session_id)

    async def get_current_plan(
        self, session_id: str, user_id: str
    ) -> Optional[Plan]:
        await self._verify_session(session_id, user_id)
        return await self._plans.find_current_plan(session_id)

    async def get_plan(self, plan_id: str, user_id: str) -> Plan:
        plan = await self._plans.find_plan(plan_id)
        if plan is None:
            raise NotFoundError("Plan not found")
        await self._verify_session(plan.session_id, user_id)
        return plan

    async def mark_task_running(self, task_id: str) -> None:
        await self._plans.update_task_status(task_id, TaskStatus.RUNNING)

    async def mark_task_completed(
        self, task_id: str, result: Optional[str] = None
    ) -> None:
        await self._plans.update_task_status(
            task_id, TaskStatus.COMPLETED, result=result
        )

    async def record_task_failure(
        self, task_id: str, plan_id: str, position: int, error: str
    ) -> bool:
        """Bump retries; return True if there's still budget left to retry.

        On exhausted retries we mark the task FAILED, BLOCK every later task,
        and flip the plan to FAILED. Caller should stop the loop.
        """
        retries = await self._plans.increment_task_retries(task_id)
        if retries <= self.MAX_TASK_RETRIES:
            return True
        await self._plans.update_task_status(
            task_id, TaskStatus.FAILED, error=error
        )
        await self._plans.block_remaining_tasks(plan_id, position)
        await self._plans.update_plan_status(
            plan_id, PlanStatus.FAILED, error=f"Task failed: {error}"
        )
        return False

    async def _verify_session(self, session_id: str, user_id: str) -> None:
        session = await self._sessions.find_by_id_and_user_id(session_id, user_id)
        if not session:
            raise NotFoundError("Session not found")
