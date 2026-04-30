"""Planner agent — decomposes a user message into an ordered task list.

The planner produces structured output via a forced `submit_plan` tool_use
(or `submit_recovery_decision` for the recovery path). The model can't emit
free text — it MUST call the submit tool, and Anthropic validates the args
against the input_schema we hand it. That replaces the older "ask for JSON
in text and pray" flow and removes a whole class of parse-failure bugs.
"""

import logging
from typing import AsyncGenerator, List, Optional

from pydantic import BaseModel, field_validator

from app.domain.models.event import (
    BaseEvent,
    ErrorEvent,
    MessageEvent,
    ToolEvent,
    ToolStatus,
)
from app.domain.models.message import Message
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.services.agents.base import BaseAgent, _make_submit_tool
from app.domain.services.prompts.planner import (
    CREATE_PLAN_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    WORKSPACE_SECTION_TEMPLATE,
)
from app.domain.services.prompts.recovery import RECOVERY_PROMPT
from app.domain.services.prompts.system import SYSTEM_PROMPT
from app.domain.services.tools.base import BaseToolkit

logger = logging.getLogger(__name__)


class PlannerTask(BaseModel):
    """One task in a planner-proposed plan.

    `title` is the bold one-liner the UI shows; `details` is optional
    markdown body (acceptance criteria, sub-bullets, deliverables).
    A bare string input is normalized to `{title: s, details: None}` —
    the model occasionally submits flat strings even when the schema
    is structured, and a stalled session is worse than a missing details.
    """

    title: str
    details: Optional[str] = None

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @classmethod
    def _coerce(cls, v: object) -> "PlannerTask":
        if isinstance(v, cls):
            return v
        if isinstance(v, str):
            return cls(title=v.strip())
        if isinstance(v, dict):
            return cls.model_validate(v)
        raise TypeError(f"Cannot coerce {type(v).__name__} to PlannerTask")


def _coerce_task_list(v: object) -> List[PlannerTask]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise TypeError("`tasks` must be a list")
    return [PlannerTask._coerce(item) for item in v]


class PlanProposal(BaseModel):
    """The plan the planner submits before any task starts running."""
    message: str = ""
    language: Optional[str] = "en"
    title: str = ""
    goal: str = ""
    tasks: List[PlannerTask] = []

    @field_validator("tasks", mode="before")
    @classmethod
    def _coerce_tasks(cls, v: object) -> List[PlannerTask]:
        return _coerce_task_list(v)


class RecoveryDecision(BaseModel):
    """Planner's choice when a task fails after exhausting retries."""
    decision: str = "abandon"  # "replan" or "abandon"
    message: str = ""
    tasks: List[PlannerTask] = []

    @field_validator("tasks", mode="before")
    @classmethod
    def _coerce_tasks(cls, v: object) -> List[PlannerTask]:
        return _coerce_task_list(v)


SUBMIT_PLAN_TOOL = "submit_plan"
SUBMIT_RECOVERY_TOOL = "submit_recovery_decision"


class PlannerAgent(BaseAgent):
    name: str = "planner"
    system_prompt: str = SYSTEM_PROMPT + PLANNER_SYSTEM_PROMPT
    # Planning is a single LLM round; far less than executor's allowance.
    max_walltime_seconds: float = 180.0

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

    async def propose_plan(
        self, message: Message, *, workspace_summary: str = ""
    ) -> AsyncGenerator[BaseEvent, None]:
        """Drive a single forced `submit_plan` tool_use call. Yields any
        partial-text MessageEvents the model emits before the tool call,
        then a synthetic MessageEvent carrying `_plan_proposal`.

        `workspace_summary` is the markdown brief from `WorkspaceSurveyor`;
        empty string means "no code context available" and the section is
        omitted entirely from the prompt."""
        workspace_section = (
            WORKSPACE_SECTION_TEMPLATE.format(summary=workspace_summary)
            if workspace_summary else ""
        )
        prompt = CREATE_PLAN_PROMPT.format(
            message=message.message,
            attachments="\n".join(message.attachments),
            workspace_section=workspace_section,
        )
        async for event in self._submit_call(
            prompt=prompt,
            tool_name=SUBMIT_PLAN_TOOL,
            tool_description="Submit the ordered plan for the user's request.",
            schema_model=PlanProposal,
            error_msg="Planner did not submit a plan",
        ):
            extracted = getattr(event, "_submitted", None)
            if extracted is None:
                yield event
                continue
            try:
                proposal = PlanProposal.model_validate(extracted)
            except Exception:
                logger.exception("Planner submitted invalid args: %s", extracted)
                yield ErrorEvent(error="Planner submitted malformed plan")
                return
            surfaced = MessageEvent(role="assistant", message=proposal.message)
            surfaced._plan_proposal = proposal  # type: ignore[attr-defined]
            yield surfaced

    async def recover_plan(
        self,
        *,
        goal: str,
        language: str,
        completed: List[str],
        failed_description: str,
        failed_error: str,
        remaining: List[str],
    ) -> AsyncGenerator[BaseEvent, None]:
        prompt = RECOVERY_PROMPT.format(
            goal=goal or "(no goal recorded)",
            language=language or "en",
            completed="\n".join(f"- {c}" for c in completed) or "- (none)",
            failed_description=failed_description,
            failed_error=failed_error,
            remaining="\n".join(f"- {r}" for r in remaining) or "- (none)",
        )
        async for event in self._submit_call(
            prompt=prompt,
            tool_name=SUBMIT_RECOVERY_TOOL,
            tool_description="Submit the replan-or-abandon decision.",
            schema_model=RecoveryDecision,
            error_msg="Recovery planner did not submit a decision",
        ):
            extracted = getattr(event, "_submitted", None)
            if extracted is None:
                yield event
                continue
            try:
                decision = RecoveryDecision.model_validate(extracted)
            except Exception:
                logger.exception("Recovery submitted invalid args: %s", extracted)
                yield ErrorEvent(error="Recovery planner submitted malformed decision")
                return
            surfaced = MessageEvent(role="assistant", message=decision.message)
            surfaced._recovery_decision = decision  # type: ignore[attr-defined]
            yield surfaced

    # ------------------------------------------------------------------
    # Shared submit-call helper
    # ------------------------------------------------------------------

    async def _submit_call(
        self,
        *,
        prompt: str,
        tool_name: str,
        tool_description: str,
        schema_model: type[BaseModel],
        error_msg: str,
    ) -> AsyncGenerator[BaseEvent, None]:
        """Run one execute() loop with a forced submit-style tool. Yields
        partial MessageEvents from streaming, suppresses the submit
        ToolEvents themselves, and yields a sentinel MessageEvent with
        `_submitted: dict` carrying the validated args. On failure yields
        ErrorEvent and returns."""
        submit_tool = _make_submit_tool(
            name=tool_name,
            description=tool_description,
            schema_model=schema_model,
        )
        self._override_tools = [submit_tool]
        self._override_tool_choice = {"type": "tool", "name": tool_name}
        self._override_terminal_tools = {tool_name}
        try:
            submitted_args: Optional[dict] = None
            async for event in self.execute(prompt):
                # Suppress the submit ToolEvent itself — internal protocol,
                # not for FE display. Capture its args from CALLED.
                if isinstance(event, ToolEvent) and event.function_name == tool_name:
                    if event.status == ToolStatus.CALLED:
                        submitted_args = dict(event.function_args or {})
                    continue
                # Forward streaming text + everything else.
                yield event

            if submitted_args is None:
                logger.error("%s: model produced no submit_* call", tool_name)
                yield ErrorEvent(error=error_msg)
                return

            sentinel = MessageEvent(role="assistant", message="")
            sentinel._submitted = submitted_args  # type: ignore[attr-defined]
            yield sentinel
        finally:
            self._override_tools = None
            self._override_tool_choice = None
            self._override_terminal_tools = None
