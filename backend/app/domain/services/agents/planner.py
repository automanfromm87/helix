"""Planner agent — decomposes a user message into an ordered task list.

The planner produces structured output via a forced `submit_plan` tool_use
(or `submit_recovery_decision` for the recovery path). The model can't emit
free text — it MUST call the submit tool, and Anthropic validates the args
against the input_schema we hand it. That replaces the older "ask for JSON
in text and pray" flow and removes a whole class of parse-failure bugs.
"""

import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from pydantic import BaseModel, field_validator

from app.domain.models.event import (
    BaseEvent,
    ErrorEvent,
    MessageEvent,
    ToolEvent,
    ToolStatus,
)
from app.domain.models.message import Message
from app.domain.external.llm import LLM
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


# Hard cap on PlannerTask.title — anything longer overflows into `details`.
# Picked to stay well under the DB column (varchar(512)), with headroom for
# UTF-8 expansion and any future ORM additions. The model is also told via
# the prompt that titles are short, but it occasionally emits Markdown
# bullet bodies into the title slot anyway — this is the structural backstop.
_TITLE_MAX_CHARS = 200


def _split_title_and_details(raw: str) -> tuple[str, Optional[str]]:
    """Best-effort split of an overgrown title into a one-liner + body.

    Strategy:
      1. Strip a leading "Details:" or "Details -" preamble — the model
         loves to use that as a prefix when it's in detail-rider mode.
      2. If the remainder still has multiple lines, the first non-empty
         line is the title; everything after is details.
      3. If still over the cap (one giant line), hard-cut at the cap.
    """
    s = raw.strip()
    s = re.sub(r"^details\s*[:\-]\s*", "", s, flags=re.IGNORECASE)
    if "\n" in s:
        head, _, tail = s.partition("\n")
        head = head.strip()
        body = tail.strip() or None
        if len(head) > _TITLE_MAX_CHARS:
            body = ((head[_TITLE_MAX_CHARS:] + "\n\n" + (body or "")).strip()) or None
            head = head[:_TITLE_MAX_CHARS].rstrip()
        return head, body
    if len(s) <= _TITLE_MAX_CHARS:
        return s, None
    return s[:_TITLE_MAX_CHARS].rstrip(), s[_TITLE_MAX_CHARS:].lstrip() or None


class PlannerTask(BaseModel):
    """One task in a planner-proposed plan.

    `title` is the bold one-liner the UI shows; `details` is optional
    markdown body (acceptance criteria, sub-bullets, deliverables).
    A bare string input is normalized to `{title: s, details: None}` —
    the model occasionally submits flat strings even when the schema
    is structured, and a stalled session is worse than a missing details.

    `explicit_non_goals` is a list of things the executor must NOT pursue
    while running this task. When the executor encounters a tool failure
    relating to one of these (e.g. "starting backend services" while doing
    a UI-only edit), it should submit success=false with the blocker
    rather than chase the rabbit hole. This is the structural backstop
    against goal drift — see `prompts/planner.py` for guidance on what
    to put here.
    """

    title: str
    details: Optional[str] = None
    explicit_non_goals: List[str] = []

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @classmethod
    def _coerce(cls, v: object) -> "PlannerTask":
        if isinstance(v, cls):
            return cls._enforce_caps(v.title, v.details)
        if isinstance(v, str):
            head, body = _split_title_and_details(v)
            return cls(title=head, details=body)
        if isinstance(v, dict):
            title = v.get("title")
            details = v.get("details")
            if isinstance(title, str) and len(title.strip()) > _TITLE_MAX_CHARS:
                head, body = _split_title_and_details(title)
                # Preserve any existing `details` by appending after the
                # overflow we just extracted.
                if isinstance(details, str) and details.strip():
                    body = f"{body}\n\n{details}".strip() if body else details.strip()
                return cls(title=head, details=body)
            return cls.model_validate(v)
        raise TypeError(f"Cannot coerce {type(v).__name__} to PlannerTask")

    @classmethod
    def _enforce_caps(cls, title: str, details: Optional[str]) -> "PlannerTask":
        if len(title) <= _TITLE_MAX_CHARS:
            return cls(title=title, details=details)
        head, body = _split_title_and_details(title)
        if details and details.strip():
            body = f"{body}\n\n{details}".strip() if body else details.strip()
        return cls(title=head, details=body)


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
    """Planner's choice when a task fails after exhausting retries.

    Four decisions, modeled after speedjs's recovery_decision:
      - replan : original strategy is broken; replace failed task AND all
                 remaining tasks with a different approach
      - split  : failed task was too coarse; replace ONLY the failed task
                 with smaller sub-tasks; remaining tasks stay
      - skip   : task is optional (verification, nice-to-have polish);
                 drop the failed task and continue with remaining as-is
      - abandon: goal can't be achieved from here; surface failure cleanly
    """
    decision: str = "abandon"  # "replan" | "split" | "skip" | "abandon"
    message: str = ""
    tasks: List[PlannerTask] = []

    @field_validator("decision", mode="before")
    @classmethod
    def _normalize_decision(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip().lower()
            if v in {"replan", "split", "skip", "abandon"}:
                return v
        # Unknown / malformed → abandon, safest default
        return "abandon"

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
        llm: LLM,
        tools: List[BaseToolkit],
    ):
        super().__init__(
            agent_id=agent_id,
            agent_repository=agent_repository,
            llm=llm,
            tools=tools,
        )

    # Tools the planner is allowed to call BEFORE submit_plan to gather
    # context (read-only / informational only). `load_skill` is the
    # critical one — without it, skills like `product-spec` that depend
    # on the planner reading their body before drafting can never fire.
    # Keep this list short on purpose; planner research is for
    # gathering context, not doing work.
    _PLANNER_RESEARCH_TOOL_NAMES: set[str] = {"load_skill"}

    async def propose_plan(
        self, message: Message, *, workspace_summary: str = ""
    ) -> AsyncGenerator[BaseEvent, None]:
        """Drive a multi-step ReAct loop terminating in `submit_plan`.

        The planner is allowed to call `load_skill` (and any other tool
        in `_PLANNER_RESEARCH_TOOL_NAMES`) BEFORE submitting, so skills
        whose bodies prescribe binding planning rules (e.g. `product-spec`'s
        PRD-extraction protocol) can actually fire. Without this, the
        planner is single-shot and skill bodies are inaccessible to it.

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
        # Multimodal: prepend image content blocks if the user attached any
        # images. Planner sees the same vision context as the executor so it
        # can incorporate "build a UI matching this screenshot" or similar.
        request: Union[str, List[Dict[str, Any]]]
        if message.image_blocks:
            request = [*message.image_blocks, {"type": "text", "text": prompt}]
        else:
            request = prompt
        # Resolve research tools from the planner's full toolkit set.
        # Only those whose names appear in the allowlist survive — others
        # (file_write, shell_exec, browser_*, etc.) stay out of the
        # planner's surface so it can't accidentally do executor work.
        research_tools = [
            t for kit in self.toolkits for t in kit.get_tools()
            if t.name in self._PLANNER_RESEARCH_TOOL_NAMES
        ]
        async for event in self._submit_call(
            prompt=request,
            tool_name=SUBMIT_PLAN_TOOL,
            tool_description="Submit the ordered plan for the user's request.",
            schema_model=PlanProposal,
            error_msg="Planner did not submit a plan",
            research_tools=research_tools,
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
        prior_failures: List[str],
        cycle_index: int,
        max_cycles: int,
    ) -> AsyncGenerator[BaseEvent, None]:
        prompt = RECOVERY_PROMPT.format(
            goal=goal or "(no goal recorded)",
            language=language or "en",
            completed="\n".join(f"- {c}" for c in completed) or "- (none)",
            failed_description=failed_description,
            failed_error=failed_error,
            remaining="\n".join(f"- {r}" for r in remaining) or "- (none)",
            prior_failures="\n".join(f"- {p}" for p in prior_failures) or "- (none)",
            cycle_index=cycle_index,
            max_cycles=max_cycles,
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
        prompt: Union[str, List[Dict[str, Any]]],
        tool_name: str,
        tool_description: str,
        schema_model: type[BaseModel],
        error_msg: str,
        research_tools: Optional[List[Any]] = None,
    ) -> AsyncGenerator[BaseEvent, None]:
        """Run one execute() loop terminating in `submit_*`. Yields
        partial MessageEvents from streaming, suppresses the submit
        ToolEvents themselves, and yields a sentinel MessageEvent with
        `_submitted: dict` carrying the validated args. On failure yields
        ErrorEvent and returns.

        When `research_tools` is provided (non-empty), the planner runs as
        a multi-step ReAct loop: it can call any of those tools first
        (e.g. `load_skill` to read a skill body), then call the submit
        tool to terminate. tool_choice stays "auto" so the model picks
        freely. When `research_tools` is None or empty, behavior reverts
        to the legacy single-shot mode (force tool_choice = submit).
        """
        submit_tool = _make_submit_tool(
            name=tool_name,
            description=tool_description,
            schema_model=schema_model,
        )
        if research_tools:
            self._override_tools = list(research_tools) + [submit_tool]
            self._override_tool_choice = None  # Auto — model picks
        else:
            self._override_tools = [submit_tool]
            self._override_tool_choice = {"type": "tool", "name": tool_name}
        self._override_terminal_tools = {tool_name}
        try:
            submitted_args: Optional[dict] = None
            saw_error = False
            async for event in self.execute(prompt):
                # Suppress the submit ToolEvent itself — internal protocol,
                # not for FE display. Capture its args from CALLED.
                if isinstance(event, ToolEvent) and event.function_name == tool_name:
                    if event.status == ToolStatus.CALLED:
                        submitted_args = dict(event.function_args or {})
                    continue
                if isinstance(event, ErrorEvent):
                    saw_error = True
                # Forward streaming text + everything else.
                yield event

            if submitted_args is None:
                # Real upstream error already surfaced — adding a generic
                # "no submit_*" message would just hide the root cause.
                if saw_error:
                    return
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
