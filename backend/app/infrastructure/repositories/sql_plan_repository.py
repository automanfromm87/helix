"""Postgres-backed PlanRepository."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.application.errors.exceptions import NotFoundError
from app.domain.models.plan import Plan, PlanStatus, Task, TaskInput, TaskStatus
from app.domain.repositories.plan_repository import PlanRepository
from app.infrastructure.models.sql import PlanRow, TaskRow

logger = logging.getLogger(__name__)


# Sentinel block we embed at the start of the `description` column to carry
# `explicit_non_goals` without an alembic migration. Backwards-compatible:
# rows without the sentinel just produce an empty list. Format chosen so it
# survives a Markdown render unchanged (HTML comments are invisible).
_NON_GOALS_SENTINEL = re.compile(
    r"^<!--HELIX_NON_GOALS:(?P<json>\[.*?\])-->\n?", re.DOTALL
)


def _encode_description(details: Optional[str], non_goals: List[str]) -> Optional[str]:
    """Combine details + non_goals into the single `description` column."""
    body = details or ""
    if non_goals:
        prefix = f"<!--HELIX_NON_GOALS:{json.dumps(non_goals, ensure_ascii=False)}-->\n"
        body = prefix + body
    return body or None


def _decode_description(raw: Optional[str]) -> Tuple[Optional[str], List[str]]:
    """Split the stored `description` back into (details, non_goals)."""
    if not raw:
        return None, []
    match = _NON_GOALS_SENTINEL.match(raw)
    if not match:
        return raw, []
    try:
        non_goals = json.loads(match.group("json"))
        if not isinstance(non_goals, list):
            non_goals = []
    except json.JSONDecodeError:
        non_goals = []
    rest = raw[match.end():]
    return (rest or None), [str(x) for x in non_goals]


def _task_row_to_domain(row: TaskRow) -> Task:
    # Legacy rows wrote everything into `description` with no `title`;
    # surface those as title-only so the UI doesn't render an empty header.
    raw_desc = row.description
    decoded_details, non_goals = _decode_description(raw_desc)
    title = row.title or (decoded_details or "")
    details = decoded_details if row.title else None
    return Task(
        id=row.task_id,
        plan_id=row.plan_id,
        position=row.position,
        title=title,
        details=details,
        explicit_non_goals=non_goals,
        status=TaskStatus(row.status),
        result=row.result,
        error=row.error,
        retries=row.retries,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


def _plan_row_to_domain(row: PlanRow) -> Plan:
    return Plan(
        id=row.plan_id,
        session_id=row.session_id,
        title=row.title,
        goal=row.goal,
        language=row.language,
        status=PlanStatus(row.status),
        error=row.error,
        tasks=[_task_row_to_domain(t) for t in row.tasks],
        recovery_count=row.recovery_count or 0,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
        commit_sha=row.commit_sha,
    )


class SqlPlanRepository(PlanRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_with_tasks(
        self,
        session_id: str,
        title: str,
        goal: str,
        language: Optional[str],
        tasks: List[TaskInput],
    ) -> Plan:
        plan_id = uuid.uuid4().hex[:16]
        async with self._session_factory() as db:
            plan_row = PlanRow(
                plan_id=plan_id,
                session_id=session_id,
                title=title,
                goal=goal,
                language=language,
                status=PlanStatus.PLANNING.value,
            )
            db.add(plan_row)
            for i, task in enumerate(tasks):
                db.add(
                    TaskRow(
                        task_id=uuid.uuid4().hex[:16],
                        plan_id=plan_id,
                        position=i,
                        title=task.title,
                        description=_encode_description(task.details, task.explicit_non_goals),
                        status=TaskStatus.PENDING.value,
                    )
                )
            await db.commit()

        # Reload with tasks attached so the caller gets a full Plan domain object.
        plan = await self.find_plan(plan_id)
        if plan is None:
            raise NotFoundError(f"Plan {plan_id} disappeared right after creation")
        return plan

    async def find_plan(self, plan_id: str) -> Optional[Plan]:
        async with self._session_factory() as db:
            row = await db.scalar(
                select(PlanRow)
                .options(selectinload(PlanRow.tasks))
                .where(PlanRow.plan_id == plan_id)
            )
            return _plan_row_to_domain(row) if row else None

    async def find_current_plan(self, session_id: str) -> Optional[Plan]:
        async with self._session_factory() as db:
            row = await db.scalar(
                select(PlanRow)
                .options(selectinload(PlanRow.tasks))
                .where(PlanRow.session_id == session_id)
                .order_by(PlanRow.created_at.desc())
                .limit(1)
            )
            return _plan_row_to_domain(row) if row else None

    async def list_plans(self, session_id: str) -> List[Plan]:
        async with self._session_factory() as db:
            result = await db.execute(
                select(PlanRow)
                .options(selectinload(PlanRow.tasks))
                .where(PlanRow.session_id == session_id)
                .order_by(PlanRow.created_at.desc())
            )
            return [_plan_row_to_domain(r) for r in result.scalars().all()]

    async def update_plan_status(
        self, plan_id: str, status: PlanStatus, error: Optional[str] = None
    ) -> None:
        values = {"status": status.value}
        if error is not None:
            values["error"] = error
        if status in (PlanStatus.COMPLETED, PlanStatus.FAILED):
            values["completed_at"] = datetime.now(timezone.utc)
        async with self._session_factory() as db:
            result = await db.execute(
                update(PlanRow).where(PlanRow.plan_id == plan_id).values(**values)
            )
            if result.rowcount == 0:
                raise NotFoundError(f"Plan {plan_id} not found")
            await db.commit()

    async def set_commit_sha(self, plan_id: str, commit_sha: str) -> None:
        async with self._session_factory() as db:
            await db.execute(
                update(PlanRow)
                .where(PlanRow.plan_id == plan_id)
                .values(commit_sha=commit_sha)
            )
            await db.commit()

    async def find_task(self, task_id: str) -> Optional[Task]:
        async with self._session_factory() as db:
            row = await db.get(TaskRow, task_id)
            return _task_row_to_domain(row) if row else None

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        values = {"status": status.value}
        if result is not None:
            values["result"] = result
        if error is not None:
            values["error"] = error
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED):
            values["completed_at"] = datetime.now(timezone.utc)
        async with self._session_factory() as db:
            qres = await db.execute(
                update(TaskRow).where(TaskRow.task_id == task_id).values(**values)
            )
            if qres.rowcount == 0:
                raise NotFoundError(f"Task {task_id} not found")
            await db.commit()

    async def increment_task_retries(self, task_id: str) -> int:
        async with self._session_factory() as db:
            row = await db.get(TaskRow, task_id)
            if row is None:
                raise NotFoundError(f"Task {task_id} not found")
            row.retries = (row.retries or 0) + 1
            await db.commit()
            return row.retries

    async def block_remaining_tasks(self, plan_id: str, after_position: int) -> int:
        async with self._session_factory() as db:
            qres = await db.execute(
                update(TaskRow)
                .where(
                    TaskRow.plan_id == plan_id,
                    TaskRow.position > after_position,
                    TaskRow.status == TaskStatus.PENDING.value,
                )
                .values(
                    status=TaskStatus.BLOCKED.value,
                    error="Blocked by upstream task failure",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            return qres.rowcount or 0

    async def unblock_remaining_tasks(self, plan_id: str, after_position: int) -> int:
        """Reverse of `block_remaining_tasks`: flip BLOCKED tasks back to
        PENDING. Used by SKIP and SPLIT recovery decisions to revive the
        rest of the plan after a task is dropped or replaced."""
        async with self._session_factory() as db:
            qres = await db.execute(
                update(TaskRow)
                .where(
                    TaskRow.plan_id == plan_id,
                    TaskRow.position > after_position,
                    TaskRow.status == TaskStatus.BLOCKED.value,
                )
                .values(
                    status=TaskStatus.PENDING.value,
                    error=None,
                    completed_at=None,
                )
            )
            await db.commit()
            return qres.rowcount or 0

    async def increment_plan_recovery_count(self, plan_id: str) -> int:
        async with self._session_factory() as db:
            row = await db.get(PlanRow, plan_id)
            if row is None:
                raise NotFoundError(f"Plan {plan_id} not found")
            row.recovery_count = (row.recovery_count or 0) + 1
            await db.commit()
            return row.recovery_count

    async def reset_running_tasks(self, plan_id: str) -> int:
        async with self._session_factory() as db:
            result = await db.execute(
                update(TaskRow)
                .where(
                    TaskRow.plan_id == plan_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                )
                .values(status=TaskStatus.PENDING.value)
            )
            await db.commit()
            return result.rowcount or 0

    async def insert_tasks_after(
        self, plan_id: str, after_position: int, tasks: List[TaskInput]
    ) -> List[Task]:
        """Make room immediately after `after_position` and insert the given
        tasks. Existing PENDING/BLOCKED rows past the cutoff are shifted
        forward by `len(tasks)`. Completed/failed rows aren't touched.
        """
        if not tasks:
            return []
        shift = len(tasks)
        async with self._session_factory() as db:
            # Bump existing pending/blocked tasks past the cutoff to make
            # room. Iterate from the highest position down so we don't trip
            # the (plan_id, position) uniqueness while shifting.
            existing = (
                await db.execute(
                    select(TaskRow)
                    .where(
                        TaskRow.plan_id == plan_id,
                        TaskRow.position > after_position,
                        TaskRow.status.in_(
                            (TaskStatus.PENDING.value, TaskStatus.BLOCKED.value)
                        ),
                    )
                    .order_by(TaskRow.position.desc())
                )
            ).scalars().all()
            for row in existing:
                row.position = row.position + shift
            await db.flush()
            new_rows: List[TaskRow] = []
            for offset, task in enumerate(tasks, start=1):
                row = TaskRow(
                    task_id=uuid.uuid4().hex[:16],
                    plan_id=plan_id,
                    position=after_position + offset,
                    title=task.title,
                    description=_encode_description(task.details, task.explicit_non_goals),
                    status=TaskStatus.PENDING.value,
                )
                db.add(row)
                new_rows.append(row)
            await db.commit()
        out: List[Task] = []
        for row in new_rows:
            t = await self.find_task(row.task_id)
            if t:
                out.append(t)
        return out

    async def replace_pending_tasks(
        self, plan_id: str, after_position: int, tasks: List[TaskInput]
    ) -> List[Task]:
        async with self._session_factory() as db:
            # Drop pending/blocked tasks past the cutoff. Completed/failed
            # tasks are history and must stay so the user can read them.
            await db.execute(
                delete(TaskRow).where(
                    TaskRow.plan_id == plan_id,
                    TaskRow.position > after_position,
                    TaskRow.status.in_(
                        (TaskStatus.PENDING.value, TaskStatus.BLOCKED.value)
                    ),
                )
            )
            new_rows: List[TaskRow] = []
            for offset, task in enumerate(tasks, start=1):
                row = TaskRow(
                    task_id=uuid.uuid4().hex[:16],
                    plan_id=plan_id,
                    position=after_position + offset,
                    title=task.title,
                    description=_encode_description(task.details, task.explicit_non_goals),
                    status=TaskStatus.PENDING.value,
                )
                db.add(row)
                new_rows.append(row)
            await db.commit()
        # Round-trip through find_task to capture defaults (timestamps).
        out: List[Task] = []
        for row in new_rows:
            task = await self.find_task(row.task_id)
            if task:
                out.append(task)
        return out
