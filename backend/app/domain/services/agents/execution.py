"""Execution agent — runs a single Task to completion.

Receives one Task's description and lets the underlying ReAct loop drive
tools until the model finalizes via `submit_task_result`. Final summary is
produced via a single `submit_summary` tool_use call.
"""

import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from pydantic import BaseModel

from app.domain.models.event import (
    BaseEvent,
    ErrorEvent,
    MessageEvent,
    ToolEvent,
    ToolStatus,
    WaitEvent,
)
from app.domain.models.message import Message
from app.domain.models.plan import Plan, Task
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.services.agents.base import (
    BaseAgent,
    ERROR_CODE_BUDGET_EXHAUSTED,
    _make_submit_tool,
)
from app.domain.services.prompts.execution import (
    EXECUTION_PROMPT,
    EXECUTION_SYSTEM_PROMPT,
    NON_GOALS_SECTION_TEMPLATE,
    SUMMARIZE_PROMPT,
)
from app.domain.services.prompts.system import SYSTEM_PROMPT
from app.domain.services.tools.base import BaseToolkit
from app.domain.services.tools.message import ASK_USER_TOOL

logger = logging.getLogger(__name__)


SUBMIT_TASK_RESULT_TOOL = "submit_task_result"
SUBMIT_SUMMARY_TOOL = "submit_summary"


class TaskResult(BaseModel):
    """Schema the executor submits when a task is done."""
    success: bool = True
    result: str = ""
    attachments: List[str] = []
    # Optional structured error string when success=False.
    error: str = ""


class SummaryResult(BaseModel):
    """Final summary the executor delivers to the user after the plan ends."""
    message: str = ""
    attachments: List[str] = []


class ExecutionAgent(BaseAgent):
    name: str = "execution"
    system_prompt: str = SYSTEM_PROMPT + EXECUTION_SYSTEM_PROMPT

    def __init__(
        self,
        agent_id: str,
        agent_repository: AgentRepository,
        tools: List[BaseToolkit],
    ):
        super().__init__(
            agent_id=agent_id,
            agent_repository=agent_repository,
            tools=tools,
        )

    async def execute_task(
        self,
        plan: Plan,
        task: Task,
        user_message: Message,
    ) -> AsyncGenerator[BaseEvent, None]:
        """Run a ReAct loop until the model calls `submit_task_result` or
        pauses for `message_ask_user`. Tools used during the loop are the
        normal toolkits PLUS the `submit_task_result` terminal tool — the
        model picks the latter when it has a final answer."""
        non_goals_section = ""
        if task.explicit_non_goals:
            items = "\n".join(f"  - {ng}" for ng in task.explicit_non_goals)
            non_goals_section = NON_GOALS_SECTION_TEMPLATE.format(items=items)
        prompt = EXECUTION_PROMPT.format(
            step=task.description,
            message=user_message.message,
            attachments="\n".join(user_message.attachments),
            language=plan.language or "en",
            non_goals_section=non_goals_section,
        )
        # If the user message carried image attachments, send them as real
        # vision content blocks so the model can actually look at them. The
        # filename text already lives in the prompt template (the path list)
        # so the model knows what's what.
        request: "str | List[Dict[str, Any]]"
        if user_message.image_blocks:
            request = [*user_message.image_blocks, {"type": "text", "text": prompt}]
        else:
            request = prompt

        # Augment the executor's normal tools with the submit-result tool.
        # No forced tool_choice — the model picks freely. Submit-result is
        # marked terminal so the loop exits cleanly when invoked.
        existing = [t for kit in self.toolkits for t in kit.get_tools()]
        submit_tool = _make_submit_tool(
            name=SUBMIT_TASK_RESULT_TOOL,
            description=(
                "Submit the final result for the current task. Call this exactly "
                "once when the task is fully complete (or has failed and cannot "
                "be retried)."
            ),
            schema_model=TaskResult,
        )
        self._override_tools = existing + [submit_tool]
        self._override_terminal_tools = {SUBMIT_TASK_RESULT_TOOL}
        try:
            submitted: Optional[dict] = None
            async for event in self.execute(request):
                # Submit-result is internal protocol; suppress its events.
                if (
                    isinstance(event, ToolEvent)
                    and event.function_name == SUBMIT_TASK_RESULT_TOOL
                ):
                    if event.status == ToolStatus.CALLED:
                        submitted = dict(event.function_args or {})
                    continue

                # Pause-tool: still surfaces the user-visible question and
                # WAIT terminator, same as before.
                if isinstance(event, ToolEvent) and event.function_name == ASK_USER_TOOL:
                    if event.status == ToolStatus.CALLING:
                        # `function_args` is typed Dict[str, Any] but a smaller
                        # model can mid-stream emit a partial tool_use whose
                        # input arrived as None / empty / non-dict. Coerce so
                        # `.get(...)` is always safe.
                        args = event.function_args if isinstance(event.function_args, dict) else {}
                        yield MessageEvent(message=args.get("text", ""))
                    elif event.status == ToolStatus.CALLED:
                        yield WaitEvent()
                        return
                    continue

                yield event

            if submitted is None:
                # Implicit-completion fallback (mirrors speedjs's
                # `Task_done_implicit`): if the loop ended cleanly with the
                # model's last assistant turn being free text and no
                # tool_use, accept that text as the task's result instead
                # of failing the task. The text was already streamed via
                # the loop's text-only exit, so we attach `_task_result`
                # to a sentinel MessageEvent (empty body) for the flow
                # layer to record the structured outcome without
                # re-rendering the same text in the UI.
                memory = await self._ensure_memory()
                last = memory.get_last_message()
                if last is not None and last.role == "assistant":
                    text = last.text()
                    if text and not last.tool_uses():
                        payload = TaskResult(success=True, result=text)
                        sentinel = MessageEvent(message="")
                        sentinel._task_result = payload.model_dump()  # type: ignore[attr-defined]
                        yield sentinel
                        return
                logger.error("Task %s ended without submit_task_result", task.id)
                yield ErrorEvent(
                    error="Executor did not submit a task result",
                    code=ERROR_CODE_BUDGET_EXHAUSTED,
                )
                return

            try:
                payload = TaskResult.model_validate(submitted)
            except Exception:
                logger.exception("submit_task_result payload invalid: %s", submitted)
                yield ErrorEvent(error="Executor submitted malformed task result")
                return

            final = MessageEvent(message=payload.result)
            final._task_result = payload.model_dump()  # type: ignore[attr-defined]
            yield final
        finally:
            self._override_tools = None
            self._override_terminal_tools = None

    async def summarize(self) -> AsyncGenerator[BaseEvent, None]:
        """Single forced `submit_summary` tool_use call for the closing
        message that goes to the user once the plan's tasks are done."""
        submit_tool = _make_submit_tool(
            name=SUBMIT_SUMMARY_TOOL,
            description="Submit the final summary message for the user.",
            schema_model=SummaryResult,
        )
        self._override_tools = [submit_tool]
        self._override_tool_choice = {"type": "tool", "name": SUBMIT_SUMMARY_TOOL}
        self._override_terminal_tools = {SUBMIT_SUMMARY_TOOL}
        try:
            submitted: Optional[dict] = None
            async for event in self.execute(SUMMARIZE_PROMPT):
                if (
                    isinstance(event, ToolEvent)
                    and event.function_name == SUBMIT_SUMMARY_TOOL
                ):
                    if event.status == ToolStatus.CALLED:
                        submitted = dict(event.function_args or {})
                    continue
                yield event

            if submitted is None:
                yield ErrorEvent(error="Summarizer did not submit a summary")
                return

            try:
                payload = SummaryResult.model_validate(submitted)
            except Exception:
                logger.exception("submit_summary payload invalid: %s", submitted)
                yield ErrorEvent(error="Summarizer submitted malformed summary")
                return

            yield MessageEvent(message=payload.message)
        finally:
            self._override_tools = None
            self._override_tool_choice = None
            self._override_terminal_tools = None
