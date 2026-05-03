"""In-memory Task.

The execution task is created via `asyncio.ensure_future` from a "detached"
helper (see `_spawn_detached`) so it's owned by the event loop, not by
whatever request context happens to call `run()`. Strong references are
held in a class-level set so the task is never GC'd while live; the
`done_callback` evicts on completion.

This isolation matters because the SSE handler uses `sse_starlette`, which
internally runs through an anyio TaskGroup. Without explicit detachment a
naively-spawned `asyncio.create_task(...)` inside that scope inherits its
cancellation lineage and dies with the request — exactly the long-running
failure mode users reported (agent stops processing the moment the user
closes the chat tab).
"""

import asyncio
import logging
import traceback
import uuid
from typing import Dict, Optional, Set

from app.domain.external.message_queue import MessageQueue
from app.domain.external.task import Task, TaskRunner
from app.infrastructure.external.message_queue.in_memory_queue import InMemoryQueue

logger = logging.getLogger(__name__)


class InMemoryTask(Task):
    _task_registry: Dict[str, "InMemoryTask"] = {}
    # Strong references to every live execution task. asyncio doesn't keep
    # them alive on its own; a missing strong ref is documented to allow
    # GC mid-flight.
    _live_execution_tasks: Set[asyncio.Task] = set()

    def __init__(self, runner: TaskRunner) -> None:
        self._runner = runner
        self._id = str(uuid.uuid4())
        self._execution_task: Optional[asyncio.Task] = None
        self._input_stream = InMemoryQueue()
        self._output_stream = InMemoryQueue()
        InMemoryTask._task_registry[self._id] = self

    @property
    def id(self) -> str:
        return self._id

    @property
    def done(self) -> bool:
        if self._execution_task is None:
            return True
        return self._execution_task.done()

    async def run(self) -> None:
        if self.done:
            self._execution_task = self._spawn_detached(self._execute_task())
            logger.info("Task %s execution started", self._id)

    def cancel(self) -> bool:
        if not self.done:
            # Capture the caller chain — historically a mystery cancellation
            # killed long-running agents and we couldn't tell who triggered
            # it. INFO-level so it's always visible.
            caller = "".join(traceback.format_stack(limit=8)[:-1])
            self._execution_task.cancel()
            logger.info(
                "Task %s cancelled by:\n%s",
                self._id, caller,
            )
            self._cleanup_registry()
            return True
        self._cleanup_registry()
        return False

    @staticmethod
    def _spawn_detached(coro) -> asyncio.Task:
        """Schedule *coro* on the running loop and detach it from the caller's
        cancellation lineage (anyio TaskGroup, sse_starlette scope, ...).

        We use `loop.create_task` directly — that always attaches to the
        loop, never to a TaskGroup — and pin a strong reference in
        `_live_execution_tasks` so GC can't collect it mid-flight.
        """
        loop = asyncio.get_running_loop()
        t = loop.create_task(coro)
        InMemoryTask._live_execution_tasks.add(t)
        t.add_done_callback(InMemoryTask._live_execution_tasks.discard)
        return t

    @property
    def input_stream(self) -> MessageQueue:
        return self._input_stream

    @property
    def output_stream(self) -> MessageQueue:
        return self._output_stream

    def _on_task_done(self) -> None:
        if self._runner:
            # Strong-ref the on_done coroutine via the same _live_execution_tasks
            # set used for the main run task. Without it, asyncio's weak refs
            # let the on_done callback get GC'd mid-execution — the runner
            # never completes its post-task cleanup (DB row finalisation,
            # sandbox unbinding) and the next session restore sees a stuck
            # RUNNING state.
            t = asyncio.create_task(
                self._runner.on_done(self),
                name=f"task-{self._id}-on-done",
            )
            InMemoryTask._live_execution_tasks.add(t)

            def _on_complete(done_t: asyncio.Task) -> None:
                InMemoryTask._live_execution_tasks.discard(done_t)
                if done_t.cancelled():
                    return
                err = done_t.exception()
                if err is not None:
                    logger.error(
                        "Task %s on_done callback failed",
                        self._id,
                        exc_info=(type(err), err, err.__traceback__),
                    )

            t.add_done_callback(_on_complete)
        self._cleanup_registry()

    def _cleanup_registry(self) -> None:
        if self._id in InMemoryTask._task_registry:
            del InMemoryTask._task_registry[self._id]
            logger.info("Task %s removed from registry", self._id)

    async def _execute_task(self) -> None:
        try:
            await self._runner.run(self)
        except asyncio.CancelledError:
            logger.info("Task %s execution cancelled", self._id)
        except Exception as e:
            logger.error("Task %s execution failed: %s", self._id, str(e))
        finally:
            self._on_task_done()

    @classmethod
    def get(cls, task_id: str) -> Optional["InMemoryTask"]:
        return cls._task_registry.get(task_id)

    @classmethod
    def create(cls, runner: TaskRunner) -> "InMemoryTask":
        return cls(runner)

    @classmethod
    async def destroy(cls) -> None:
        # Snapshot then iterate — cancel() mutates the registry.
        for task in list(cls._task_registry.values()):
            task.cancel()
            if task._runner:
                await task._runner.destroy()
        cls._task_registry.clear()

    def __repr__(self) -> str:
        return f"InMemoryTask(id={self._id}, done={self.done})"
