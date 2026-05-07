from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import asyncio

from sqlalchemy import text

from app.core.config import get_settings
from app.infrastructure.storage.postgres import get_postgres
from app.infrastructure.models.sql import Base
from app.interfaces.dependencies import get_agent_service, get_session_repository
from app.interfaces.api.routes import router
from app.infrastructure.logging import setup_logging
from app.interfaces.errors.exception_handlers import register_exception_handlers

setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


_INTERRUPT_TOOL_RESULT = (
    "The backend process was restarted while this tool was running. "
    "The actual side effect is unknown — verify state before retrying."
)


async def _recover_in_flight_sessions() -> None:
    """Repair memory + flip status for sessions stranded by a crash.

    For each in-flight session:
      1. Load each agent memory the session uses (planner + execution).
      2. Append synthetic is_error tool_results for any unanswered tool_use
         in the last assistant turn — keeps Anthropic's wire-format invariant.
      3. Flip session.status to WAITING so the flow's resume branch handles it.
    """
    from app.interfaces.dependencies import (
        get_agent_repository,
        get_agent_service,
        get_plan_repository,
    )

    session_repo = get_session_repository()
    agent_repo = get_agent_repository()
    plan_repo = get_plan_repository()
    domain_service = get_agent_service()._agent_domain_service  # type: ignore[attr-defined]

    pairs = await session_repo.list_in_flight_sessions()
    if not pairs:
        return

    async def _recover_one(session_id: str, agent_id: str) -> tuple[int, int, bool]:
        """Returns (dangling_tool_uses_closed, running_tasks_reset, auto_resumed)."""
        try:
            # Memories are independent — heal them in parallel.
            memories = await asyncio.gather(
                agent_repo.get_memory(agent_id, "planner"),
                agent_repo.get_memory(agent_id, "execution"),
            )
            closed = 0
            saves = []
            for name, memory in zip(("planner", "execution"), memories):
                n = memory.close_dangling_tool_uses(_INTERRUPT_TOOL_RESULT)
                if n:
                    closed += n
                    saves.append(agent_repo.save_memory(agent_id, name, memory))
            if saves:
                await asyncio.gather(*saves)

            # Plan-level: a task left RUNNING by the crash is invisible to
            # `Plan.next_pending()` (which only walks PENDING). Flip back.
            tasks_reset = 0
            current_plan = await plan_repo.find_current_plan(session_id)
            if current_plan is not None:
                tasks_reset = await plan_repo.reset_running_tasks(current_plan.id)

            # Auto-resume: re-create the task runner and re-enqueue the
            # user's last message. Transparent across dev-mode reload
            # and rolling restarts. Falls back to WAITING on failure
            # (e.g. sandbox container actually gone).
            resumed = False
            try:
                resumed = await domain_service.resume_in_flight(session_id)
            except Exception:
                logger.exception("resume_in_flight raised for session %s", session_id)

            if not resumed:
                await session_repo.mark_session_waiting(session_id)
            return closed, tasks_reset, resumed
        except Exception:
            logger.exception("Failed to recover session %s", session_id)
            return 0, 0, False

    results = await asyncio.gather(*(_recover_one(s, a) for s, a in pairs))
    closed_total = sum(c for c, _, _ in results)
    tasks_total = sum(t for _, t, _ in results)
    resumed_total = sum(1 for _, _, r in results if r)
    logger.info(
        "Recovered %d in-flight session(s); closed %d dangling tool_use(s); "
        "reset %d stranded RUNNING task(s); auto-resumed %d",
        len(results), closed_total, tasks_total, resumed_total,
    )


async def _sandbox_janitor_loop(interval_seconds: int) -> None:
    """Periodically reap sandbox containers that no session row points at.

    Note: a *completed* session keeps its sandbox — many dev workflows leave
    a server running after the agent finishes the plan. The sandbox is only
    killed when the session itself is deleted (or never existed = true orphan).
    """
    from app.infrastructure.external.sandbox.factory import get_sandbox_cls

    sandbox_cls = get_sandbox_cls()
    repo = get_session_repository()
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            referenced_ids = await repo.get_known_sandbox_ids()
            reaped = await asyncio.to_thread(sandbox_cls.reap_orphans, referenced_ids)
            if reaped:
                logger.info("Sandbox janitor reaped %d container(s)", reaped)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Sandbox janitor iteration failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup - Helix AI Agent initializing")

    pg = get_postgres()
    await pg.initialize()
    # Auto-create schema on first boot. For real schema migrations later, swap
    # this for alembic.
    async with pg.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight in-place migration: add `sessions.project_id` to repos
        # that were created before projects existed. Idempotent.
        await conn.execute(text(
            "ALTER TABLE sessions "
            "ADD COLUMN IF NOT EXISTS project_id VARCHAR(64) "
            "REFERENCES projects(project_id) ON DELETE SET NULL"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_sessions_project_id ON sessions(project_id)"
        ))
        # Composite index for find_last_user_message: WHERE session_id = ? AND
        # event_type = 'message' ORDER BY id DESC LIMIT 1. The (session_id,
        # id) index alone has to walk back through every tool/task/plan
        # event before finding a message; this composite makes it O(1).
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_session_events_session_type_id "
            "ON session_events(session_id, event_type, id)"
        ))
        # Per-session toggle: when true, attached context files are reached
        # only via the `retrieve` tool, never dumped into the prompt.
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS "
            "retrieval_only_context BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # Project / session prompt snapshot columns (added when Project gained content).
        await conn.execute(text(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS system_prompt TEXT"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS system_prompt TEXT"
        ))
        # Project-level attachments + shared memory (workspace upgrade).
        await conn.execute(text(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb"
        ))
        await conn.execute(text(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS shared_memory TEXT"
        ))
        # LLM call telemetry: cache hit accounting added later.
        await conn.execute(text(
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS cache_read_tokens INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS cache_creation_tokens INTEGER NOT NULL DEFAULT 0"
        ))
        # Cached planner-context snapshot of the sandbox project layout.
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS workspace_summary TEXT"
        ))
        # Task title/details split. Legacy rows have description-only and no
        # title; the empty-string default keeps NOT NULL happy. The frontend
        # falls back to `description` when `title` is blank.
        await conn.execute(text(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS title VARCHAR(512) NOT NULL DEFAULT ''"
        ))
        await conn.execute(text("ALTER TABLE tasks ALTER COLUMN description DROP NOT NULL"))
        # Recovery cycle counter — caps replan-loop runaway when the planner
        # keeps choosing replan after every failure.
        await conn.execute(text(
            "ALTER TABLE plans ADD COLUMN IF NOT EXISTS recovery_count INTEGER NOT NULL DEFAULT 0"
        ))
        # Plan-as-version: auto-commit SHA produced when a plan completes.
        await conn.execute(text(
            "ALTER TABLE plans ADD COLUMN IF NOT EXISTS commit_sha VARCHAR(40)"
        ))
    logger.info("Postgres schema ensured")

    # Crash recovery: a previous backend run was killed mid-task. For every
    # session that was PENDING/RUNNING at the time, close any dangling
    # tool_use blocks in agent memory (otherwise the next Anthropic call
    # rejects the conversation as malformed) and flip status to WAITING so
    # the flow's resume branch picks up on the user's next message.
    try:
        await _recover_in_flight_sessions()
    except Exception as e:
        logger.warning("In-flight session recovery skipped: %s", e)

    # Reap any sandbox containers the previous (crashed) backend run left
    # behind — anything labeled `helix.managed=true` not referenced by an
    # existing session is removed.
    try:
        from app.infrastructure.external.sandbox.factory import get_sandbox_cls

        sandbox_cls = get_sandbox_cls()
        known_ids = await get_session_repository().get_known_sandbox_ids()
        reaped = await asyncio.to_thread(sandbox_cls.reap_orphans, known_ids)
        if reaped:
            logger.info("Reaped %d orphan sandbox container(s) at startup", reaped)
    except Exception as e:
        logger.warning("Sandbox orphan reap skipped: %s", e)

    janitor_task: asyncio.Task | None = None
    if settings.sandbox_janitor_interval_seconds > 0:
        janitor_task = asyncio.create_task(
            _sandbox_janitor_loop(settings.sandbox_janitor_interval_seconds),
            name="sandbox_janitor",
        )

    try:
        yield
    finally:
        logger.info("Application shutdown - Helix AI Agent terminating")
        if janitor_task:
            janitor_task.cancel()
            try:
                await janitor_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Sandbox janitor shutdown raised: %s", e)
        await pg.shutdown()
        try:
            await asyncio.wait_for(get_agent_service().shutdown(), timeout=30.0)
            logger.info("AgentService shutdown completed successfully")
        except asyncio.TimeoutError:
            logger.warning("AgentService shutdown timed out after 30 seconds")
        except Exception:
            logger.exception("Error during AgentService cleanup")


app = FastAPI(title="Helix AI Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/livez", tags=["health"], include_in_schema=False)
async def livez() -> dict:
    """Liveness probe — process is up. Cheap, no I/O. k8s / docker-compose
    healthcheck targets this; failing it triggers a restart."""
    return {"status": "ok"}


@app.get("/readyz", tags=["health"], include_in_schema=False)
async def readyz() -> dict:
    """Readiness probe — DB reachable, can serve traffic. Failing it pulls
    the pod out of the load-balancer rotation but does NOT restart it."""
    from sqlalchemy import text
    from app.infrastructure.storage.postgres import get_postgres
    pg = get_postgres()
    try:
        async with pg.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        # 503 status so the orchestrator marks us unready.
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"db unreachable: {e}")
    return {"status": "ready"}


register_exception_handlers(app)
app.include_router(router, prefix="/api/v1")
