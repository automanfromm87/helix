"""ReAct loop driven directly against the Anthropic Messages API.

Long-running properties:
  * Conversation history is persisted to Postgres after every turn (memory
    snapshot), so a process restart can resume any session.
  * `system` and `tools` are stamped with `cache_control: ephemeral` so long
    sessions stay cheap.
  * `context_management.clear_tool_uses_20250919` is enabled per call, letting
    Anthropic prune stale tool results server-side when input grows.

The agent never blocks on user input from inside the loop. When the model
calls `message_ask_user`, the loop returns immediately and leaves the
tool_use unanswered in memory; the resume path (see `roll_back`) fills the
tool_result with the user's next message.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.domain.models.event import (
    BaseEvent,
    ErrorEvent,
    MessageEvent,
    ToolEvent,
    ToolStatus,
)
from app.domain.models.message import Message
from app.domain.models.memory import Memory
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.models.conv_message import (
    ContentBlock,
    ConvMessage,
    ImageBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    message_from_api,
)
from app.application.errors.exceptions import ServiceUnavailableError
from app.domain.services.tools.base import BaseToolkit, Tool
from app.domain.services.tools.message import ASK_USER_TOOL
from app.domain.services.agents.protection import (
    LLMError,
    LoopGuard,
    ModelOutputTruncatedError,
    ModelRefusalError,
    TRUNCATION_RETRY_MAX_TOKENS,
    classify_api_exception,
    is_pause_turn,
    is_refusal,
    is_truncated,
    refusal_text,
    should_retry,
    truncate_tool_content,
    validate_tool_input,
)
from app.domain.models.tool_result import ToolResult, TOOL_RESULT_SANDBOX_UNAVAILABLE
from app.infrastructure.external.llm import complete_stream

logger = logging.getLogger(__name__)


_DEFAULT_CONTEXT_MANAGEMENT: Dict[str, Any] = {
    "edits": [
        {
            "type": "clear_tool_uses_20250919",
            # Trigger early so the long tail of long-running tasks doesn't
            # carry stale tool_uses for free. Threshold is conservative
            # enough that short tasks never even hit it.
            "trigger": {"type": "input_tokens", "value": 20000},
            "keep": {"type": "tool_uses", "value": 4},
            "clear_at_least": {"type": "input_tokens", "value": 3000},
        }
    ]
}


# Tools that should pause the loop instead of producing a tool_result inline.
_PAUSE_TOOLS = {ASK_USER_TOOL}


# Error code attached to ErrorEvents that signal the agent's framework budget
# (walltime / iteration cap / silent text-only exit) rather than a real task
# failure. The flow uses this to skip the retry+replan path — replanning
# wouldn't help, the next task hits the same wall.
ERROR_CODE_BUDGET_EXHAUSTED = "budget_exhausted"


class _SubmitToolkit:
    """Toolkit-shim used as the `toolkit` field of synthesized submit tools.

    Submit tools (`submit_plan` / `submit_task_result` / etc.) are an internal
    structured-output protocol — they carry the validated JSON the agent
    wants to hand back. The wrapper agents (PlannerAgent, ExecutionAgent)
    swallow their ToolEvents before they reach the FE, so we just need a
    `name` for the `ToolEvent.tool_name` field on the slim chance one leaks.
    """
    name = "submit"


_SUBMIT_TOOLKIT = _SubmitToolkit()


def _make_submit_tool(
    *,
    name: str,
    description: str,
    schema_model: type,
) -> Tool:
    """Synthesize a `submit_*` Tool whose input_schema is derived from a
    pydantic model. The Python implementation is a no-op — the structured
    output IS the tool_use input itself, and the agent loop reads it from
    the ToolEvent before the empty tool_result ever matters."""
    from app.domain.services.tools.base import _strip_titles

    async def _noop(**_: Any) -> ToolResult:
        return ToolResult(success=True)

    schema = _strip_titles(schema_model.model_json_schema())
    return Tool(
        toolkit=_SUBMIT_TOOLKIT,
        name=name,
        description=description,
        input_schema=schema,
        fn=_noop,
    )


# Streaming-output emit cadence. We coalesce text deltas into MessageEvents
# at most every `_STREAM_EMIT_INTERVAL` seconds OR every `_STREAM_EMIT_CHARS`
# new characters — whichever fires first. Tighter values feel snappier but
# multiply Postgres writes (output_stream is persisted) and FE re-renders.
# Tuned so a typical 1500-char turn produces ~5 partials, not ~10.
_STREAM_EMIT_CHARS: int = 300
_STREAM_EMIT_INTERVAL: float = 0.5


class BaseAgent(ABC):
    name: str = ""
    system_prompt: str = ""
    max_iterations: int = 100
    max_retries: int = 3
    retry_interval: float = 1.0
    # Hard wall-clock cap on a single execute() invocation. The loop checks
    # this between every model call. Subclasses can override; planner is fast
    # so it's tightened, executor stays larger for genuinely-long tasks.
    max_walltime_seconds: float = 1800.0

    # tool_choice: None = auto, "none" = disable tools.
    tool_choice: Optional[str] = None

    def __init__(
        self,
        agent_id: str,
        agent_repository: AgentRepository,
        tools: List[BaseToolkit] = (),
    ) -> None:
        self._agent_id = agent_id
        self._repository = agent_repository
        self.toolkits: List[BaseToolkit] = list(tools)
        self.memory: Optional[Memory] = None
        # Memoized request payload pieces. system_prompt is class-level
        # immutable; tools list can change when MCPToolkit warms up
        # mid-session, so we key the tools cache on (count, name-tuple).
        self.__system_blocks: Optional[List[Dict[str, Any]]] = None
        self.__tools_payload_key: Optional[tuple] = None
        self.__tools_payload: List[Dict[str, Any]] = []
        # Per-call overrides — set by helper methods (propose_plan etc.)
        # that need to swap the tool surface for one execute() invocation.
        # Cleared in `finally`; not thread-safe but each agent instance
        # processes one call at a time.
        self._override_tools: Optional[List[Tool]] = None
        self._override_tool_choice: Optional[Any] = None
        self._override_terminal_tools: Optional[set[str]] = None

    # ------------------------------------------------------------------
    # Tool registry
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> Optional[Tool]:
        if self._override_tools is not None:
            for t in self._override_tools:
                if t.name == name:
                    return t
            return None
        for kit in self.toolkits:
            t = kit.get_tool(name)
            if t:
                return t
        return None

    def get_tools(self) -> List[Tool]:
        if self._override_tools is not None:
            return list(self._override_tools)
        return [t for kit in self.toolkits for t in kit.get_tools()]

    def _terminal_tool_names(self) -> set[str]:
        return self._override_terminal_tools or set()

    # ------------------------------------------------------------------
    # Memory plumbing
    # ------------------------------------------------------------------

    async def _ensure_memory(self) -> Memory:
        if self.memory is None:
            self.memory = await self._repository.get_memory(self._agent_id, self.name)
        return self.memory

    async def _persist(self) -> None:
        assert self.memory is not None
        await self._repository.save_memory(self._agent_id, self.name, self.memory)

    async def _close_assistant_turn(
        self,
        memory: Memory,
        tool_uses: List["ToolUseBlock"],
        existing: Dict[str, "ToolResultBlock"],
        orphan_reason: str,
    ) -> None:
        """Persist a user turn that answers EVERY tool_use in the just-emitted
        assistant turn — using `existing` results when present, synthesizing
        an `is_error=True` tool_result for any uses left unanswered.

        Anthropic strictly requires that every assistant `tool_use` have a
        matching `tool_result` in the immediately-following user turn. Our
        bail-out paths (LoopGuard trips mid-dispatch, validation failures
        that exhaust the failure streak) used to return without persisting
        the user turn, leaving an orphan tool_use that poisoned the entire
        session — every subsequent API call hit a parse failure on the
        Anthropic side and the SDK saw an empty stream. This helper makes
        it impossible to leak orphans by forcing the caller to commit the
        user turn before yielding ErrorEvent and returning."""
        if not tool_uses:
            return
        completed: List[ToolResultBlock] = []
        for use in tool_uses:
            block = existing.get(use.id)
            if block is None:
                block = ToolResultBlock(
                    tool_use_id=use.id,
                    content=orphan_reason,
                    is_error=True,
                )
            completed.append(block)
        memory.add_message(ConvMessage(role="user", content=completed))
        await self._persist()

    async def memory_checkpoint(self) -> int:
        """Snapshot point for `restore_memory`. Returns the current message
        count — pass it back later to truncate to exactly this state."""
        memory = await self._ensure_memory()
        return len(memory.messages)

    async def restore_memory(self, checkpoint: int) -> int:
        """Truncate memory back to the snapshot point. Returns the number of
        messages dropped (0 if already at or below the checkpoint).

        Used by the flow when a task ends without a clean submit — the noisy
        ReAct trail from the failed attempt would otherwise prime the next
        task to repeat the same death loop."""
        memory = await self._ensure_memory()
        if checkpoint >= len(memory.messages):
            return 0
        dropped = len(memory.messages) - checkpoint
        memory.messages = memory.messages[:checkpoint]
        await self._persist()
        return dropped

    # ------------------------------------------------------------------
    # Request materialization + task-transition ack
    # ------------------------------------------------------------------

    @staticmethod
    def _materialize_request(
        request: "str | List[Dict[str, Any]]",
    ) -> List["ContentBlock"]:
        """Convert the public `execute(request)` argument into a content
        block list ready to drop into a ConvMessage. Tolerant of malformed
        list entries — anything unrecognized is dropped, and an all-empty
        result falls back to a single empty TextBlock so downstream
        invariants (last-block exists, cache marker) still hold."""
        if isinstance(request, str):
            return [TextBlock(text=request)]
        blocks: List[ContentBlock] = []
        for raw in request:
            if not isinstance(raw, dict):
                continue
            btype = raw.get("type")
            if btype == "text":
                blocks.append(TextBlock(text=raw.get("text", "")))
            elif btype == "image":
                src = raw.get("source") or {}
                if isinstance(src, dict) and src.get("type") in {"base64", "url"}:
                    blocks.append(ImageBlock(source=src))
        if not blocks:
            blocks = [TextBlock(text="")]
        return blocks

    def _dangling_submit_ack(self, memory: Memory) -> List["ContentBlock"]:
        """Return synthetic tool_result blocks that close any unanswered
        terminal submit_* tool_use(s) in the last assistant turn.

        Empty list when there's nothing to close — i.e. the previous turn
        wasn't an assistant turn, or none of its tool_uses were terminal
        submits, or those tool_uses already have matching tool_results in
        a later user turn.

        This is the "boundary" mechanism: between tasks, the prior
        submit_task_result tool_use gets answered with a textual ack in
        the SAME user turn that introduces the next task. The model sees
        a clear closure marker right next to the new task description,
        so its attention re-anchors instead of drifting back to whatever
        tool result was most recent before the close.
        """
        last = memory.get_last_message() if hasattr(memory, "get_last_message") else None
        if last is None:
            # Best-effort fallback when Memory doesn't expose get_last_message.
            msgs = getattr(memory, "messages", None) or []
            last = msgs[-1] if msgs else None
        if last is None or last.role != "assistant":
            return []
        terminal_names = self._terminal_tool_names()
        if not terminal_names:
            return []
        # Collect terminal tool_uses; skip non-terminal (those will get
        # normal tool dispatch next time around if any).
        terminal_uses = [
            b for b in last.content
            if isinstance(b, ToolUseBlock) and b.name in terminal_names
        ]
        if not terminal_uses:
            return []
        return [
            ToolResultBlock(
                tool_use_id=use.id,
                content=(
                    f"({use.name} acknowledged — proceeding to next task)"
                ),
            )
            for use in terminal_uses
        ]

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def execute(
        self,
        request: "str | List[Dict[str, Any]]",
    ) -> AsyncGenerator[BaseEvent, None]:
        """Run a ReAct loop until the model emits a final text answer or
        a pause-tool (e.g. message_ask_user). Yields ToolEvents inline and a
        single final MessageEvent on completion.

        `request` is either a plain text prompt OR a list of pre-built
        Anthropic content blocks (e.g. `[image_block, image_block, text_block]`)
        for multimodal turns. The list form lets callers send image/text
        mixes without the agent layer needing a file_storage dependency.

        Task-transition ack: when memory's last turn is an assistant turn
        ending with an unanswered terminal submit_* tool_use (i.e. the
        previous task closed and we're starting a new one), this method
        merges the synthetic tool_result that closes the prior tool_use
        AND the new task content into a SINGLE user turn. The ack message
        ("(submit_task_result acknowledged — proceeding to next task)")
        gives the model a token-level visible boundary so its attention
        re-anchors on the new task instead of being pulled by the prior
        task's tool noise. Pattern borrowed from speedjs's plan_act.ml.
        """
        memory = await self._ensure_memory()
        new_blocks = self._materialize_request(request)
        ack_blocks = self._dangling_submit_ack(memory)
        if ack_blocks:
            # Single-turn ack-merge: tool_result(s) closing prior submit_* +
            # new request content all in one user turn. Anthropic accepts
            # mixed tool_result + text/image blocks in a user turn.
            merged: List[ContentBlock] = list(ack_blocks) + list(new_blocks)
            memory.add_message(ConvMessage(role="user", content=merged))
        else:
            memory.add_message(ConvMessage(role="user", content=list(new_blocks)))
        await self._persist()

        guard = LoopGuard()
        deadline = time.monotonic() + self.max_walltime_seconds

        # Endgame trigger: how close to budget exhaustion before we force the
        # model to invoke its terminal submit-* tool. Without this, a stuck
        # ReAct loop spins to the iteration cap and then exits silently —
        # leaving the executor with no submitted result and the flow with no
        # actionable error to react to.
        #
        # Trigger is iteration-count only — wall-time elapsed is NOT a
        # signal that the model is stuck, because a single slow tool call
        # (sandbox shell, git op) can burn most of the wall-clock budget
        # without the model misbehaving. Forcing submit_task_result while
        # the model is mid-thought just produces a useless empty submit.
        endgame_iter_threshold = max(self.max_iterations - 2, 1)

        # Set when an iteration ends with text-only output but the agent has
        # terminal tools — forces tool_choice on the *next* iteration so the
        # model can't keep skipping submit_*. Reset every iteration after the
        # endgame check consumes it.
        force_terminal_next = False

        for iteration in range(self.max_iterations):
            if time.monotonic() > deadline:
                logger.warning(
                    "Agent %s exceeded walltime budget of %.0fs",
                    self.name, self.max_walltime_seconds,
                )
                yield ErrorEvent(
                    error=(
                        f"Task exceeded {self.max_walltime_seconds:.0f}s walltime — "
                        "aborting to avoid an unbounded run. Split the work into smaller steps."
                    ),
                    code=ERROR_CODE_BUDGET_EXHAUSTED,
                )
                return
            elapsed = self.max_walltime_seconds - (deadline - time.monotonic())
            in_endgame = (
                self._terminal_tool_names()
                and self._override_tool_choice is None
                and (
                    iteration >= endgame_iter_threshold
                    or force_terminal_next
                )
            )
            force_terminal_next = False  # consumed
            forced_choice: Optional[Dict[str, Any]] = None
            if in_endgame:
                # Pick the first terminal tool — for the executor this is
                # `submit_task_result`. Forcing tool_choice means the model
                # can't emit free text on its way out; it MUST hand back a
                # structured success/failure report.
                terminal_name = next(iter(self._terminal_tool_names()))
                forced_choice = {"type": "tool", "name": terminal_name}
                logger.info(
                    "Agent %s entering endgame at iter=%d elapsed=%.1fs — forcing %s",
                    self.name, iteration, elapsed, terminal_name,
                )

            message_id = uuid.uuid4().hex[:16]
            assistant: Optional[ConvMessage] = None
            saved_choice = self._override_tool_choice
            if forced_choice is not None:
                self._override_tool_choice = forced_choice
            try:
                try:
                    async for ev in self._call_model_with_retries(message_id):
                        if isinstance(ev, ConvMessage):
                            assistant = ev
                        else:
                            yield ev
                except ModelOutputTruncatedError as e:
                    logger.error("Model output truncated twice for agent %s", self.name)
                    yield ErrorEvent(error=str(e))
                    return
                except ModelRefusalError as e:
                    yield ErrorEvent(
                        error=f"The model declined to respond: {e}",
                    )
                    return
                except LLMError as e:
                    yield ErrorEvent(error=e.user_message())
                    return
                except Exception as e:
                    logger.exception("Model call failed in agent %s", self.name)
                    yield ErrorEvent(error=f"Model call failed: {e}")
                    return
            finally:
                # Always restore the per-call tool_choice, even if we returned
                # early via an exception path — otherwise the endgame override
                # would leak into a future execute() invocation.
                self._override_tool_choice = saved_choice

            if assistant is None:
                yield ErrorEvent(error="Empty model response")
                return

            tool_uses = assistant.tool_uses()
            assistant_text = assistant.text()
            # Finalize the streamed text bubble. The streaming layer emits
            # partial=True chunks on a 300-char / 0.5s cadence, so the tail
            # of a turn is often left unflushed and shows up in the UI as a
            # mid-word cutoff ("No tests y"). Without a partial=False
            # closer, the FE bubble also stays in "streaming" state forever
            # — visible whenever the model emits text alongside tool_uses
            # (the common ReAct shape), since the legacy finalizer below
            # only fires in the text-only branch.
            if assistant_text:
                yield MessageEvent(
                    message=assistant_text,
                    message_id=message_id,
                    partial=False,
                )
            if not tool_uses:
                if not assistant_text:
                    # Preserve legacy behavior: still emit an (empty)
                    # MessageEvent for the text-only no-text edge case so
                    # downstream consumers see the closing event.
                    yield MessageEvent(
                        message="",
                        message_id=message_id,
                        partial=False,
                    )
                # No terminal tools (plan / summary / chat agents) → text is
                # the natural exit.
                if not self._terminal_tool_names():
                    return
                # Has terminal tools (executor) → text-only is a protocol
                # violation: the wrapper expects submit_* and will roll back
                # if we just return. Treat as retryable — nudge with a user
                # message and force tool_choice on the next iteration.
                terminal_name = next(iter(self._terminal_tool_names()))
                logger.warning(
                    "Agent %s emitted text without %s; nudging and forcing "
                    "tool_choice on next iter (iter=%d)",
                    self.name, terminal_name, iteration,
                )
                memory.add_message(ConvMessage(
                    role="user",
                    content=[TextBlock(text=(
                        f"You replied with text but the task isn't formally "
                        f"closed. Call {terminal_name} now to submit the result."
                    ))],
                ))
                await self._persist()
                force_terminal_next = True
                continue

            # Three-phase tool dispatch so independent calls run in parallel:
            # classify → emit CALLING → gather → emit CALLED in model order.
            phase_one_results: Dict[str, ToolResultBlock] = {}
            runnable: List[tuple[ToolUseBlock, Tool]] = []
            paused = False
            for use in tool_uses:
                tool = self.get_tool(use.name)
                if not tool:
                    yield ErrorEvent(error=f"Unknown tool: {use.name}")
                    phase_one_results[use.id] = ToolResultBlock(
                        tool_use_id=use.id,
                        content=f"Unknown tool: {use.name}",
                        is_error=True,
                    )
                    continue

                stop = guard.record_call(use.name, use.input)
                if stop:
                    await self._close_assistant_turn(
                        memory, tool_uses, phase_one_results,
                        "Tool dispatch aborted by loop-guard before execution",
                    )
                    yield ErrorEvent(error=stop)
                    return

                if use.name in _PAUSE_TOOLS:
                    # Pause-tools serialize the conversation; whatever follows
                    # in the same turn would be answered by the user's reply.
                    # Pop CALLING+CALLED events for the pause tool and stop.
                    logger.info("tool_call agent=%s name=%s (pause)", self.name, use.name)
                    yield ToolEvent(
                        status=ToolStatus.CALLING,
                        tool_call_id=use.id,
                        tool_name=tool.toolkit.name,
                        function_name=use.name,
                        function_args=use.input,
                    )
                    yield ToolEvent(
                        status=ToolStatus.CALLED,
                        tool_call_id=use.id,
                        tool_name=tool.toolkit.name,
                        function_name=use.name,
                        function_args=use.input,
                        function_result=ToolResult(success=True),
                    )
                    paused = True
                    break

                validation_err = validate_tool_input(tool.input_schema, use.input)
                if validation_err:
                    failed = ToolResult(success=False, message=validation_err)
                    yield ToolEvent(
                        status=ToolStatus.CALLING,
                        tool_call_id=use.id,
                        tool_name=tool.toolkit.name,
                        function_name=use.name,
                        function_args=use.input,
                    )
                    yield ToolEvent(
                        status=ToolStatus.CALLED,
                        tool_call_id=use.id,
                        tool_name=tool.toolkit.name,
                        function_name=use.name,
                        function_args=use.input,
                        function_result=failed,
                    )
                    phase_one_results[use.id] = ToolResultBlock(
                        tool_use_id=use.id,
                        content=truncate_tool_content(_serialize_tool_result(failed)),
                        is_error=True,
                    )
                    stop = guard.record_failure(validation_err)
                    if stop:
                        await self._close_assistant_turn(
                            memory, tool_uses, phase_one_results,
                            "Tool dispatch aborted by loop-guard after validation failure",
                        )
                        yield ErrorEvent(error=stop)
                        return
                    continue

                runnable.append((use, tool))

            if paused:
                # Memory already contains the assistant turn with the pending
                # tool_use; we leave it unanswered until the next user input.
                return

            # Phase 2: emit CALLING up front then invoke in parallel
            for use, tool in runnable:
                logger.info(
                    "tool_call agent=%s name=%s args_keys=%s",
                    self.name, use.name, sorted(use.input.keys()) if isinstance(use.input, dict) else "?",
                )
                yield ToolEvent(
                    status=ToolStatus.CALLING,
                    tool_call_id=use.id,
                    tool_name=tool.toolkit.name,
                    function_name=use.name,
                    function_args=use.input,
                )

            invocation_results: Dict[str, ToolResult] = {}
            if runnable:
                gathered = await asyncio.gather(
                    *(self._invoke_tool_with_retries(tool, use.input) for use, tool in runnable),
                    return_exceptions=False,
                )
                for (use, _tool), result in zip(runnable, gathered):
                    invocation_results[use.id] = result

            # Phase 3: emit CALLED + assemble tool_results in original order
            tool_results: List[ToolResultBlock] = []
            for use in tool_uses:
                if use.id in phase_one_results:
                    tool_results.append(phase_one_results[use.id])
                    continue
                if use.id not in invocation_results:
                    continue  # guarded out (paused)
                tool = self.get_tool(use.name)
                if tool is None:
                    # Should be impossible — every entry in invocation_results
                    # came from `runnable`, which is only populated after
                    # get_tool() returned non-None earlier in the loop. But
                    # `assert` strips under -O and a real None would crash with
                    # `AssertionError` in dev / `AttributeError` in prod.
                    # Skip the row instead and log so we'd notice if invariant
                    # ever broke.
                    logger.warning(
                        "tool %s disappeared between phase 1 and phase 3 "
                        "(invariant violation, skipping)", use.name,
                    )
                    continue
                result = invocation_results[use.id]
                logger.info(
                    "tool_done agent=%s name=%s success=%s",
                    self.name, use.name, result.success,
                )
                yield ToolEvent(
                    status=ToolStatus.CALLED,
                    tool_call_id=use.id,
                    tool_name=tool.toolkit.name,
                    function_name=use.name,
                    function_args=use.input,
                    function_result=result,
                )
                # Skill payloads MUST keep their full body — truncating
                # mid-document would feed the model garbage knowledge.
                # Three-tier cache makes the size cheap after the first
                # turn anyway.
                serialized = _serialize_tool_result(result)
                if tool.toolkit.name != "skill":
                    serialized = truncate_tool_content(serialized)
                tool_results.append(
                    ToolResultBlock(
                        tool_use_id=use.id,
                        content=serialized,
                        is_error=not result.success,
                    )
                )
                if result.success:
                    guard.record_success()
                else:
                    stop = guard.record_failure(result.message or "tool failure")
                    if stop:
                        # Existing results so far (phase_one + executed
                        # uses up to this point) — close the rest with
                        # synthetic is_error blocks so memory stays valid.
                        existing_dict = {b.tool_use_id: b for b in tool_results}
                        await self._close_assistant_turn(
                            memory, tool_uses, existing_dict,
                            "Tool dispatch aborted by loop-guard mid-execution",
                        )
                        yield ErrorEvent(error=stop)
                        return

            memory.add_message(ConvMessage(role="user", content=list(tool_results)))
            await self._persist()

            # Terminal tool: caller wanted a structured submit_* tool to
            # end the loop after one successful invocation. Memory now
            # contains the assistant turn + tool_result pair, so it stays
            # valid for resume; we just stop driving the model.
            terminal = self._terminal_tool_names()
            if terminal and any(use.name in terminal for use in tool_uses):
                return
        else:
            yield ErrorEvent(
                error="Maximum iteration count reached, failed to complete the task",
                code=ERROR_CODE_BUDGET_EXHAUSTED,
            )

    # ------------------------------------------------------------------
    # Resumption
    # ------------------------------------------------------------------

    async def roll_back(self, message: Message) -> None:
        """Called when a new user message arrives mid-conversation.

        If the last assistant turn has unanswered tool_uses for any pause-tool
        (e.g. message_ask_user), we synthesize tool_result blocks containing
        the user's message so the conversation resumes coherently. Otherwise
        we drop the last assistant turn so the user message can re-anchor.
        """
        memory = await self._ensure_memory()
        last = memory.get_last_message()
        if not last or last.role != "assistant":
            return

        pending_pauses = [
            b for b in last.content if isinstance(b, ToolUseBlock) and b.name in _PAUSE_TOOLS
        ]
        if pending_pauses:
            results = [
                ToolResultBlock(tool_use_id=b.id, content=message.message)
                for b in pending_pauses
            ]
            memory.add_message(ConvMessage(role="user", content=list(results)))
            await self._persist()
            return

        if any(isinstance(b, ToolUseBlock) for b in last.content):
            # Stranded tool_use without a result — drop it; the new user
            # message will start a fresh thread.
            memory.roll_back()
            await self._persist()

    # ------------------------------------------------------------------
    # Model invocation
    # ------------------------------------------------------------------

    async def _call_model_with_retries(
        self, message_id: str
    ) -> AsyncGenerator[Any, None]:
        """Streaming wrapper. Yields:
          * `MessageEvent` — partial text, all sharing `message_id`
          * `ConvMessage` — terminator carrying the full assistant turn

        Errors are classified via `protection.classify_api_exception`:
          * Retryable (transport / 429 / 529 / 5xx) → exponential backoff
            with jitter, honoring `Retry-After` when the API supplied it.
          * Fatal (400 / 401 / 403 / 404 / context-window) → re-raised
            immediately so `execute()` can yield a clean ErrorEvent.
        Truncation and refusal pass through unchanged — they're handled
        in `_call_model_streaming` itself."""
        last_err: Optional[LLMError] = None
        for attempt in range(self.max_retries):
            try:
                async for emission in self._call_model_streaming(message_id):
                    yield emission
                return
            except (ModelOutputTruncatedError, ModelRefusalError):
                raise
            except LLMError as e:
                last_err = e
            except Exception as e:
                last_err = classify_api_exception(e)

            wait = should_retry(last_err, attempt, self.max_retries)
            if wait is None:
                logger.error(
                    "Model call FATAL agent=%s err=%s: %s",
                    self.name, type(last_err).__name__, last_err,
                )
                raise last_err
            logger.warning(
                "Model call attempt %d/%d failed (%s); sleeping %.1fs",
                attempt + 1, self.max_retries, type(last_err).__name__, wait,
            )
            await asyncio.sleep(wait)
        # Exhausted retries on a retryable error.
        assert last_err is not None
        logger.error("Model call exhausted retries: %s", last_err)
        raise last_err

    async def _call_model_streaming(
        self, message_id: str
    ) -> AsyncGenerator[Any, None]:
        memory = await self._ensure_memory()

        api_messages = [m.to_api() for m in memory.get_messages()]
        system_blocks = self._build_system_blocks()
        api_tools = self._build_tools_payload()
        tool_choice = self._build_tool_choice_payload()
        ctx_mgmt = _DEFAULT_CONTEXT_MANAGEMENT if api_tools else None
        # Third cache breakpoint — messages[-1].content[-1]. Combined with the
        # system + tools breakpoints this gives a 3-tier sliding-window cache:
        # turn N writes the cache up through this turn's last block, turn N+1
        # hits it (history hasn't moved) and writes a new entry on its own
        # last block. Multi-turn agent loops see most of the prompt as a
        # cache HIT instead of fresh input.
        _mark_last_message_cacheable(api_messages)

        async def _one_call(max_tokens: Optional[int]) -> AsyncGenerator[Any, None]:
            """Yields MessageEvent partials, finally `('payload', dict)`."""
            last_emit_at = 0.0
            buf: list[str] = []
            last_emit_len = 0
            payload: Optional[Dict[str, Any]] = None
            async for chunk in complete_stream(
                messages=api_messages,
                system=system_blocks,
                tools=api_tools or None,
                tool_choice=tool_choice,
                context_management=ctx_mgmt,
                max_tokens=max_tokens,
            ):
                if chunk["type"] == "text_delta":
                    buf.append(chunk["text"])
                    total = sum(map(len, buf))
                    grew = total - last_emit_len
                    now = time.monotonic()
                    if grew >= _STREAM_EMIT_CHARS or (now - last_emit_at) >= _STREAM_EMIT_INTERVAL:
                        last_emit_at = now
                        last_emit_len = total
                        yield MessageEvent(
                            message="".join(buf),
                            message_id=message_id,
                            partial=True,
                        )
                elif chunk["type"] == "final":
                    payload = chunk["payload"]
            if payload is None:
                raise RuntimeError("Stream ended without final payload")
            yield ("payload", payload)

        payload: Optional[Dict[str, Any]] = None
        async for emission in _one_call(max_tokens=None):
            if isinstance(emission, tuple) and emission[0] == "payload":
                payload = emission[1]
            else:
                yield emission

        assert payload is not None
        if is_truncated(payload):
            logger.warning(
                "Agent %s response truncated by max_tokens; retrying with %d",
                self.name, TRUNCATION_RETRY_MAX_TOKENS,
            )
            async for emission in _one_call(max_tokens=TRUNCATION_RETRY_MAX_TOKENS):
                if isinstance(emission, tuple) and emission[0] == "payload":
                    payload = emission[1]
                else:
                    yield emission
            assert payload is not None
            if is_truncated(payload):
                raise ModelOutputTruncatedError(
                    f"Model output exceeded {TRUNCATION_RETRY_MAX_TOKENS} tokens "
                    "twice in a row — the task likely needs to be split into smaller steps."
                )

        # Carrying a refusal in memory poisons subsequent turns; surface it
        # without persisting and let the caller handle the user-facing reason.
        if is_refusal(payload):
            reason = refusal_text(payload)
            logger.warning("Agent %s refusal: %s", self.name, reason[:200])
            raise ModelRefusalError(reason)

        if is_pause_turn(payload):
            logger.info("Agent %s pause_turn — continuing on next iteration", self.name)

        assistant = message_from_api(payload)
        memory.add_message(assistant)
        await self._persist()
        logger.debug("Model response (agent=%s): %s", self.name, assistant)
        yield assistant

    def _build_system_blocks(self) -> Optional[List[Dict[str, Any]]]:
        if not self.system_prompt:
            return None
        if self.__system_blocks is None:
            self.__system_blocks = [
                {
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        return self.__system_blocks

    def _build_tools_payload(self) -> List[Dict[str, Any]]:
        tools = self.get_tools()
        if not tools:
            return []
        # Memoize keyed on the current toolset identity. Equality on the
        # name tuple is enough — toolkit definitions don't mutate at runtime,
        # and rebuilding on add/remove is correct.
        key = tuple(t.name for t in tools)
        if key != self.__tools_payload_key:
            payload = [t.to_anthropic() for t in tools]
            # Mark the last entry for prompt-cache reuse across turns.
            payload[-1] = {**payload[-1], "cache_control": {"type": "ephemeral"}}
            self.__tools_payload_key = key
            self.__tools_payload = payload
        return self.__tools_payload

    def _build_tool_choice_payload(self) -> Optional[Dict[str, Any]]:
        choice = (
            self._override_tool_choice
            if self._override_tool_choice is not None
            else self.tool_choice
        )
        if choice is None:
            return None
        if isinstance(choice, dict):
            return choice
        if choice == "none":
            return {"type": "none"}
        return None

    # ------------------------------------------------------------------
    # Tool invocation
    # ------------------------------------------------------------------

    # Hard wall-clock cap on a single tool.ainvoke() call. Any individual
    # tool internally hanging (e.g. CDP socket dies, browser_use reconnect
    # spinning, sandbox shell wedge) gets killed at this boundary instead
    # of consuming the entire task walltime budget. Tuned higher than the
    # typical longest legitimate operation (a slow shell_exec finishing) but
    # well below task walltime so the model gets a fast actionable error.
    tool_call_timeout_seconds: float = 120.0

    async def _invoke_tool_with_retries(self, tool: Tool, args: Dict[str, Any]) -> ToolResult:
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                return await asyncio.wait_for(
                    tool.ainvoke(args),
                    timeout=self.tool_call_timeout_seconds,
                )
            except asyncio.TimeoutError:
                msg = (
                    f"Tool '{tool.name}' did not complete within "
                    f"{self.tool_call_timeout_seconds:.0f}s — aborting this call. "
                    "If the underlying operation is genuinely long-running, "
                    "use the background+wait pattern (e.g. shell_exec & + shell_wait)."
                )
                logger.warning("%s (args=%s)", msg, args)
                # Return immediately — retrying a hang of the same shape will
                # almost certainly hang the same way.
                return ToolResult(success=False, message=msg)
            except ServiceUnavailableError as e:
                # Backing service is plainly down — no point burning retries.
                # LoopGuard upstream sees the same error twice in a row and
                # aborts the task cleanly.
                logger.info("Tool %s skipped: %s", tool.name, e.msg)
                return ToolResult(
                    success=False,
                    message=e.msg,
                    code=TOOL_RESULT_SANDBOX_UNAVAILABLE,
                )
            except Exception as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_interval)
                    continue
                logger.exception("Tool %s failed (args=%s)", tool.name, args)
        return ToolResult(success=False, message=last_error)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_tool_result(result: ToolResult) -> str:
    try:
        return result.model_dump_json()
    except Exception:
        return str(result)


def _mark_last_message_cacheable(api_messages: List[Dict[str, Any]]) -> None:
    """Place a `cache_control: ephemeral` marker on the last content block of
    the last message — the third breakpoint in the system / tools / messages
    cache hierarchy. Idempotent; no-op on empty messages."""
    if not api_messages:
        return
    content = api_messages[-1].get("content")
    if not content:
        return
    last_block = content[-1]
    if not isinstance(last_block, dict):
        return
    last_block.setdefault("cache_control", {"type": "ephemeral"})


