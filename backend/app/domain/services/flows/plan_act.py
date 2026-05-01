"""Plan/Act flow with DB-backed Plans + Tasks.

Per user message:
  PLANNING  → planner produces task list, persisted to DB
  EXECUTING → loop pending tasks in `position` order, run executor on each
  SUMMARIZING → executor delivers final summary message
  COMPLETED → emit final PlanEvent, exit loop

Failure handling: a task that errors out gets one retry. A second failure
fails the task, marks every later task BLOCKED, fails the plan, and exits.
"""

import logging
from enum import Enum
from typing import AsyncGenerator, Optional

from app.application.services.plan_service import PlanService
from app.domain.external.browser import Browser
from app.domain.external.sandbox import Sandbox
from app.domain.external.search import SearchEngine
from app.domain.models.event import (
    BaseEvent,
    DoneEvent,
    ErrorEvent,
    MessageEvent,
    PlanEvent,
    TaskEvent,
    TitleEvent,
    WaitEvent,
)
from app.domain.models.message import Message
from app.domain.models.plan import Plan, PlanStatus, Task, TaskInput, TaskStatus
from app.domain.models.session import SessionStatus
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.plan_repository import PlanRepository
from app.domain.repositories.session_repository import SessionRepository
from app.domain.services.agents.base import ERROR_CODE_BUDGET_EXHAUSTED
from app.domain.services.agents.execution import ExecutionAgent
from app.domain.services.agents.planner import PlannerAgent
from app.domain.services.flows.base import BaseFlow
from app.domain.services.tools.browser import BrowserToolkit
from app.domain.services.tools.file import FileToolkit
from app.domain.services.tools.mcp import MCPToolkit
from app.domain.services.tools.message import MessageToolkit
from app.domain.services.tools.search import SearchToolkit
from app.domain.services.tools.shell import ShellToolkit
from app.domain.repositories.skill_repository import SkillRepository
from app.domain.services.tools.skill import SkillToolkit, render_skill_index
from app.domain.services.workspace_surveyor import WorkspaceSurveyor

logger = logging.getLogger(__name__)


# Hard cap on replan cycles per Plan. After this many recover-replan loops
# we force abandon, regardless of what the planner wants — replans that
# fail in series rarely produce a working alternative.
MAX_RECOVERY_CYCLES: int = 2


class FlowStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    RECOVERING = "recovering"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanActFlow(BaseFlow):
    def __init__(
        self,
        agent_id: str,
        agent_repository: AgentRepository,
        session_id: str,
        session_repository: SessionRepository,
        plan_repository: PlanRepository,
        sandbox: Sandbox,
        browser: Browser,
        mcp_tool: MCPToolkit,
        search_engine: Optional[SearchEngine] = None,
        extra_system_prompt: Optional[str] = None,
        skill_repository: Optional[SkillRepository] = None,
    ):
        self._agent_id = agent_id
        self._repository = agent_repository
        self._session_id = session_id
        self._session_repository = session_repository
        self._plan_service = PlanService(
            plan_repository=plan_repository,
            session_repository=session_repository,
        )
        self._plan_repository = plan_repository
        self._sandbox = sandbox
        self._surveyor = WorkspaceSurveyor()
        self.status = FlowStatus.IDLE
        self.plan: Optional[Plan] = None

        tools = [
            ShellToolkit(sandbox),
            BrowserToolkit(browser),
            FileToolkit(sandbox),
            MessageToolkit(),
            mcp_tool,
        ]
        if search_engine:
            tools.append(SearchToolkit(search_engine))
        if skill_repository is not None and skill_repository.list():
            tools.append(SkillToolkit(skill_repository))

        self.planner = PlannerAgent(
            agent_id=self._agent_id,
            agent_repository=self._repository,
            tools=tools,
        )
        self.executor = ExecutionAgent(
            agent_id=self._agent_id,
            agent_repository=self._repository,
            tools=tools,
        )

        # Skill index goes into the system prompt as a one-line-per-skill
        # menu so the model can decide what to load. Do this BEFORE the
        # session-specific extra_system_prompt so user/project overrides
        # still get the last word.
        skill_index = render_skill_index(skill_repository) if skill_repository else ""
        if skill_index:
            self.planner.system_prompt = self.planner.system_prompt + "\n\n" + skill_index
            self.executor.system_prompt = self.executor.system_prompt + "\n\n" + skill_index

        if extra_system_prompt:
            extra = "\n\n" + extra_system_prompt.strip()
            self.planner.system_prompt = self.planner.system_prompt + extra
            self.executor.system_prompt = self.executor.system_prompt + extra

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def run(self, message: Message) -> AsyncGenerator[BaseEvent, None]:
        session = await self._session_repository.find_by_id(self._session_id)
        if not session:
            yield ErrorEvent(error=f"Session {self._session_id} not found")
            return

        # If a previous turn left the session WAITING (message_ask_user), the
        # incoming message is a *response* to that ask — we should resume the
        # current plan rather than building a new one.
        resuming = session.status == SessionStatus.WAITING
        if not resuming:
            await self.executor.roll_back(message)
            await self.planner.roll_back(message)

        await self._session_repository.update_status(
            self._session_id, SessionStatus.RUNNING
        )

        if resuming:
            self.plan = await self._plan_repository.find_current_plan(self._session_id)
            if self.plan:
                # A backend crash mid-task leaves one task stranded in
                # RUNNING. `Plan.next_pending()` only walks PENDING, so
                # without this self-heal the resume silently skips the
                # unfinished task. Idempotent for normal pause/resume too
                # (where no task is RUNNING).
                reset = await self._plan_repository.reset_running_tasks(self.plan.id)
                if reset:
                    logger.info(
                        "Reset %d stranded RUNNING task(s) on resume of plan %s",
                        reset, self.plan.id,
                    )
                    self.plan = await self._plan_repository.find_plan(self.plan.id)
            self.status = FlowStatus.EXECUTING if self.plan else FlowStatus.PLANNING
        else:
            self.status = FlowStatus.PLANNING

        logger.info(
            "Agent %s flow start; status=%s, message=%r",
            self._agent_id, self.status, message.message[:80],
        )

        while True:
            if self.status == FlowStatus.PLANNING:
                async for event in self._do_planning(
                    message, cached_workspace_summary=session.workspace_summary,
                ):
                    yield event
            elif self.status == FlowStatus.EXECUTING:
                async for event in self._do_executing(message):
                    yield event
                    # Wait events terminate the run cleanly; outer loop in the
                    # task runner is what restarts us.
                    if isinstance(event, WaitEvent):
                        return
            elif self.status == FlowStatus.SUMMARIZING:
                async for event in self.executor.summarize():
                    yield event
                self.status = FlowStatus.COMPLETED
            elif self.status == FlowStatus.COMPLETED:
                if self.plan:
                    await self._plan_service.mark_plan_completed(self.plan.id)
                    self.plan = await self._plan_repository.find_plan(self.plan.id)
                    if self.plan:
                        yield PlanEvent(plan=self.plan, status=PlanStatus.COMPLETED)
                await self._invalidate_workspace_summary()
                yield DoneEvent()
                self.status = FlowStatus.IDLE
                return
            elif self.status == FlowStatus.FAILED:
                if self.plan:
                    self.plan = await self._plan_repository.find_plan(self.plan.id)
                    if self.plan:
                        yield PlanEvent(plan=self.plan, status=PlanStatus.FAILED)
                await self._invalidate_workspace_summary()
                yield DoneEvent()
                self.status = FlowStatus.IDLE
                return

    def is_done(self) -> bool:
        return self.status == FlowStatus.IDLE

    async def _invalidate_workspace_summary(self) -> None:
        """Mark the cached brief as dirty so the next plan re-surveys.

        Called at the end of a plan (completed or failed) since most plans
        write something. Skipping per-tool tracking keeps this simple at
        the cost of one extra survey per user message — acceptable.
        """
        try:
            await self._session_repository.update_workspace_summary(
                self._session_id, None
            )
        except Exception:
            logger.debug(
                "Workspace summary invalidation failed for session %s",
                self._session_id, exc_info=True,
            )

    async def _ensure_workspace_summary(self, cached: Optional[str]) -> str:
        """Return a workspace brief — reuse `cached` if present, else run
        the surveyor and persist the result. Empty string is a valid
        cached value (the project is non-code), distinguished from "never
        generated" (None) so a non-code session doesn't pay the survey
        cost on every plan.
        """
        if cached is not None:
            return cached
        try:
            summary = await self._surveyor.summarize(self._sandbox)
        except Exception:
            logger.exception("Workspace survey failed; planning without it")
            return ""
        try:
            await self._session_repository.update_workspace_summary(
                self._session_id, summary
            )
        except Exception:
            logger.warning(
                "Failed to cache workspace summary for session %s; "
                "next plan will regenerate", self._session_id,
            )
        return summary

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------
    async def _do_planning(
        self, message: Message, *, cached_workspace_summary: Optional[str]
    ) -> AsyncGenerator[BaseEvent, None]:
        workspace_summary = await self._ensure_workspace_summary(
            cached_workspace_summary
        )
        proposal = None
        async for event in self.planner.propose_plan(
            message, workspace_summary=workspace_summary
        ):
            extracted = getattr(event, "_plan_proposal", None)
            if extracted is not None:
                proposal = extracted
                # The planner's MessageEvent shows the user how the request was
                # understood — yield it for chat history.
                yield MessageEvent(role="assistant", message=event.message)
                continue
            yield event

        if proposal is None or not proposal.tasks:
            # Planner couldn't produce tasks. Mark planning failure and bail.
            self.status = FlowStatus.COMPLETED
            return

        self.plan = await self._plan_service.start_plan(
            session_id=self._session_id,
            title=proposal.title,
            goal=proposal.goal,
            language=proposal.language,
            tasks=[
                TaskInput(
                    title=t.title,
                    details=t.details,
                    explicit_non_goals=t.explicit_non_goals,
                )
                for t in proposal.tasks
            ],
        )
        await self._plan_service.mark_plan_executing(self.plan.id)
        self.plan = await self._plan_repository.find_plan(self.plan.id)
        if self.plan and self.plan.title:
            yield TitleEvent(title=self.plan.title)
        if self.plan:
            yield PlanEvent(plan=self.plan, status=PlanStatus.EXECUTING)
        self.status = FlowStatus.EXECUTING

    async def _do_executing(
        self, message: Message
    ) -> AsyncGenerator[BaseEvent, None]:
        if not self.plan:
            self.status = FlowStatus.COMPLETED
            return

        # Always read fresh from DB — task statuses can mutate from outside the
        # in-memory `Plan` snapshot during retries.
        self.plan = await self._plan_repository.find_plan(self.plan.id)
        if not self.plan:
            self.status = FlowStatus.COMPLETED
            return

        task = self.plan.next_pending()
        if task is None:
            # All done → summarize.
            self.status = FlowStatus.SUMMARIZING
            return

        async for event in self._run_task(message, task):
            yield event

    async def _run_task(
        self, message: Message, task: Task
    ) -> AsyncGenerator[BaseEvent, None]:
        await self._plan_service.mark_task_running(task.id)
        task.status = TaskStatus.RUNNING
        yield TaskEvent(task=task, status=TaskStatus.RUNNING)

        # Snapshot the executor's memory BEFORE this attempt. Failure path
        # rolls back to here so the next task / retry doesn't inherit the
        # noisy ReAct trail from a stuck attempt. Successful tasks keep
        # their memory for downstream summarization.
        memory_checkpoint = await self.executor.memory_checkpoint()

        had_error: Optional[str] = None
        had_error_code: Optional[str] = None
        task_result: Optional[str] = None
        wait_hit = False
        try:
            async for event in self.executor.execute_task(self.plan, task, message):
                if isinstance(event, ErrorEvent):
                    had_error = event.error
                    had_error_code = getattr(event, "code", None)
                    # Don't yield the raw ErrorEvent — wrap into TaskEvent below.
                    continue
                # WaitEvent: pause for user input. The task stays RUNNING.
                if event.type == "wait":
                    wait_hit = True
                    yield event
                    return
                # The executor's final MessageEvent carries `_task_result`.
                result_payload = getattr(event, "_task_result", None)
                if result_payload is not None:
                    task_result = result_payload.get("result") or ""
                    if not result_payload.get("success", True):
                        had_error = result_payload.get("error") or "Task reported failure"
                yield event
        except Exception as e:
            logger.exception("Task %s execution raised", task.id)
            had_error = str(e)

        if wait_hit:
            return

        if had_error:
            # Always roll the executor's memory back to before this attempt.
            # The ReAct trail of a failed task is pure noise for whatever
            # comes next (retry, replan, or summary) — leaving it in place
            # is what produced the original death-loop behavior.
            dropped = await self.executor.restore_memory(memory_checkpoint)
            if dropped:
                logger.info(
                    "Rolled back %d executor memory message(s) after task %s failure",
                    dropped, task.id,
                )

            # Budget-exhausted (walltime / iteration cap / silent exit) is a
            # framework problem, not a task-feasibility problem. Replanning
            # produces fresh tasks that hit the same wall. Skip the retry +
            # recovery dance and go straight to abandon.
            if had_error_code == ERROR_CODE_BUDGET_EXHAUSTED:
                await self._plan_service.mark_task_failed_terminal(
                    task.id, self.plan.id, task.position, had_error
                )
                failed = await self._plan_repository.find_task(task.id)
                if failed:
                    yield TaskEvent(task=failed, status=TaskStatus.FAILED)
                self.status = FlowStatus.FAILED
                return

            can_retry = await self._plan_service.record_task_failure(
                task.id, self.plan.id, task.position, had_error
            )
            if can_retry:
                # Reset task to PENDING for the next iteration.
                await self._plan_service.mark_task_running(task.id)
                # On retry path we still emit a TaskEvent FAILED snapshot so
                # the FE can show "retrying" UX if it wants.
                refreshed = await self._plan_repository.find_task(task.id)
                if refreshed:
                    yield TaskEvent(task=refreshed, status=TaskStatus.RUNNING)
                # Loop again next tick by leaving status EXECUTING — but we
                # need to reset task status to PENDING so next_pending() picks
                # it up.
                await self._plans_reset_for_retry(task.id)
                return
            # Out of retries: ask the planner whether the plan can recover.
            # `record_task_failure` already cascaded BLOCKED + plan FAILED;
            # `_do_recovery` may reverse those if the planner picks replan.
            async for event in self._do_recovery(task, had_error):
                yield event
            return

        await self._plan_service.mark_task_completed(task.id, result=task_result)
        completed = await self._plan_repository.find_task(task.id)
        if completed:
            yield TaskEvent(task=completed, status=TaskStatus.COMPLETED)
        # Memory compaction is handled server-side by the
        # `clear_tool_uses_20250919` context_management policy on every
        # call (see _DEFAULT_CONTEXT_MANAGEMENT in agents/base.py). A
        # client-side compact pass would mutate already-cached message
        # bytes and force the entire prompt-cache prefix to be rebuilt
        # on the next call — exactly the regression we just fixed.

    async def _plans_reset_for_retry(self, task_id: str) -> None:
        """Flip a task back to PENDING for another attempt."""
        await self._plan_repository.update_task_status(task_id, TaskStatus.PENDING)

    # ------------------------------------------------------------------
    # Recovery: replan or abandon after retries are exhausted
    # ------------------------------------------------------------------

    async def _do_recovery(
        self, failed_task: Task, error: str
    ) -> AsyncGenerator[BaseEvent, None]:
        """Consult the planner. On replan we splice new tasks into the plan
        and resume EXECUTING; on abandon we leave the cascade in place and
        let the executor summarize what was achieved."""
        self.status = FlowStatus.RECOVERING

        plan = await self._plan_repository.find_plan(self.plan.id) if self.plan else None
        if plan is None:
            self.status = FlowStatus.FAILED
            return

        # Hard cap on replan cycles. Without this a planner that keeps
        # picking "replan" can produce an unbounded series of failed
        # task-batches (the original death-loop symptom — 11 → 19 tasks).
        cycle_index = await self._plan_repository.increment_plan_recovery_count(plan.id)
        if cycle_index > MAX_RECOVERY_CYCLES:
            logger.warning(
                "Plan %s exceeded %d recovery cycles — forcing abandon",
                plan.id, MAX_RECOVERY_CYCLES,
            )
            failed = await self._plan_repository.find_task(failed_task.id)
            if failed:
                yield TaskEvent(task=failed, status=TaskStatus.FAILED)
            self.status = FlowStatus.FAILED
            return

        completed = [t.description for t in plan.tasks if t.status == TaskStatus.COMPLETED]
        remaining = [
            t.description
            for t in plan.tasks
            if t.position > failed_task.position
            and t.status in (TaskStatus.PENDING, TaskStatus.BLOCKED)
        ]
        prior_failures = [
            f"{t.description} — error: {t.error or '(unknown)'}"
            for t in plan.tasks
            if t.status == TaskStatus.FAILED and t.id != failed_task.id
        ]

        decision = None
        async for event in self.planner.recover_plan(
            goal=plan.goal,
            language=plan.language or "en",
            completed=completed,
            failed_description=failed_task.description,
            failed_error=error,
            remaining=remaining,
            prior_failures=prior_failures,
            cycle_index=cycle_index,
            max_cycles=MAX_RECOVERY_CYCLES,
        ):
            extracted = getattr(event, "_recovery_decision", None)
            if extracted is not None:
                decision = extracted
                yield MessageEvent(role="assistant", message=event.message)
                continue
            yield event

        # Planner failed to produce a usable decision → keep the FAILED
        # cascade record_task_failure already wrote.
        if decision is None:
            failed = await self._plan_repository.find_task(failed_task.id)
            if failed:
                yield TaskEvent(task=failed, status=TaskStatus.FAILED)
            self.status = FlowStatus.FAILED
            return

        if decision.decision == "replan" and decision.tasks:
            # Reverse the FAILED cascade: plan goes back to EXECUTING, the
            # blocked tasks are deleted, and new tasks take their slot.
            new_tasks = [
                TaskInput(
                    title=t.title,
                    details=t.details,
                    explicit_non_goals=t.explicit_non_goals,
                )
                for t in decision.tasks
            ]
            await self._plan_repository.replace_pending_tasks(
                plan.id, failed_task.position, new_tasks
            )
            await self._plan_service.mark_plan_executing(plan.id)
            self.plan = await self._plan_repository.find_plan(plan.id)
            if self.plan:
                yield PlanEvent(plan=self.plan, status=PlanStatus.EXECUTING)
            failed = await self._plan_repository.find_task(failed_task.id)
            if failed:
                yield TaskEvent(task=failed, status=TaskStatus.FAILED)
            logger.info(
                "Plan %s recovered via replan; %d new task(s)",
                plan.id, len(decision.tasks),
            )
            self.status = FlowStatus.EXECUTING
            return

        if decision.decision == "split" and decision.tasks:
            # SPLIT: insert sub-tasks AFTER the failed task, keep remaining
            # pending tasks (un-block them since the cascade marked them
            # BLOCKED on failure). The failed task itself stays FAILED for
            # history; the sub-tasks run before whatever was queued.
            new_tasks = [
                TaskInput(
                    title=t.title,
                    details=t.details,
                    explicit_non_goals=t.explicit_non_goals,
                )
                for t in decision.tasks
            ]
            await self._plan_repository.insert_tasks_after(
                plan.id, failed_task.position, new_tasks
            )
            await self._plan_repository.unblock_remaining_tasks(
                plan.id, failed_task.position
            )
            await self._plan_service.mark_plan_executing(plan.id)
            self.plan = await self._plan_repository.find_plan(plan.id)
            if self.plan:
                yield PlanEvent(plan=self.plan, status=PlanStatus.EXECUTING)
            failed = await self._plan_repository.find_task(failed_task.id)
            if failed:
                yield TaskEvent(task=failed, status=TaskStatus.FAILED)
            logger.info(
                "Plan %s recovered via split; %d sub-task(s) inserted",
                plan.id, len(decision.tasks),
            )
            self.status = FlowStatus.EXECUTING
            return

        if decision.decision == "skip":
            # SKIP: the failed task is treated as optional. Drop it from the
            # active queue (it stays FAILED in history) and revive the
            # remaining BLOCKED tasks so execution resumes after it.
            await self._plan_repository.unblock_remaining_tasks(
                plan.id, failed_task.position
            )
            await self._plan_service.mark_plan_executing(plan.id)
            self.plan = await self._plan_repository.find_plan(plan.id)
            if self.plan:
                yield PlanEvent(plan=self.plan, status=PlanStatus.EXECUTING)
            failed = await self._plan_repository.find_task(failed_task.id)
            if failed:
                yield TaskEvent(task=failed, status=TaskStatus.FAILED)
            logger.info(
                "Plan %s recovered via skip on task %s",
                plan.id, failed_task.id,
            )
            self.status = FlowStatus.EXECUTING
            return

        # Abandon (also the fallback when "replan"/"split" came back without
        # any tasks): keep the FAILED cascade, let the executor summarize
        # what was actually delivered. Plan stays FAILED — but flow status
        # moves to SUMMARIZING so we still produce a closing message.
        failed = await self._plan_repository.find_task(failed_task.id)
        if failed:
            yield TaskEvent(task=failed, status=TaskStatus.FAILED)
        logger.info(
            "Plan %s recovery decision: %s", plan.id, decision.decision
        )
        self.status = FlowStatus.FAILED
