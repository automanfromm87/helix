from typing import Optional, AsyncGenerator, List
import asyncio
import logging
from datetime import datetime
from app.application.errors.exceptions import NotFoundError
from app.domain.models.session import Session, SessionStatus
from app.domain.external.sandbox import Sandbox
from app.domain.external.search import SearchEngine
from app.domain.models.event import BaseEvent, ErrorEvent, DoneEvent, MessageEvent, WaitEvent, AgentEvent
from pydantic import TypeAdapter
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.session_repository import SessionRepository
from app.domain.services.agent_task_runner import AgentTaskRunner
from app.domain.external.task import Task
from typing import Type
from app.domain.external.file import FileStorage
from app.domain.models.file import FileInfo
from app.domain.repositories.mcp_repository import MCPRepository
from app.domain.repositories.plan_repository import PlanRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.skill_repository import SkillRepository, SkillStore
from app.domain.services.skills import LayeredSkillRepository

# Setup logging
logger = logging.getLogger(__name__)

class AgentDomainService:
    """
    Agent domain service, responsible for coordinating the work of planning agent and execution agent
    """
    
    def __init__(
        self,
        agent_repository: AgentRepository,
        session_repository: SessionRepository,
        sandbox_cls: Type[Sandbox],
        task_cls: Type[Task],
        file_storage: FileStorage,
        mcp_repository: MCPRepository,
        plan_repository: PlanRepository,
        search_engine: Optional[SearchEngine] = None,
        project_repository: Optional[ProjectRepository] = None,
        skill_repository: Optional[SkillRepository] = None,
        skill_store: Optional[SkillStore] = None,
    ):
        self._repository = agent_repository
        self._session_repository = session_repository
        self._sandbox_cls = sandbox_cls
        self._search_engine = search_engine
        self._task_cls = task_cls
        self._file_storage = file_storage
        self._mcp_repository = mcp_repository
        self._plan_repository = plan_repository
        self._project_repository = project_repository
        self._skill_repository = skill_repository
        self._skill_store = skill_store
        # Per-session lock prevents the check-and-create race in
        # `_create_task`: two concurrent `chat()` calls (e.g. an SSE
        # reconnect happening while the first message is still spinning up
        # a sandbox) used to each spawn their own container, leaving one
        # orphaned. Lock granularity is per-session-id so unrelated
        # sessions still proceed in parallel.
        self._task_creation_locks: dict[str, asyncio.Lock] = {}
        logger.info("AgentDomainService initialization completed")

    def _task_creation_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._task_creation_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._task_creation_locks[session_id] = lock
        return lock
            
    async def shutdown(self) -> None:
        """Clean up all Agent's resources"""
        logger.info("Starting to close all Agents")
        await self._task_cls.destroy()
        logger.info("All agents closed successfully")

    async def _create_task(self, session: Session) -> Task:
        """Create a new agent task. Persists session once at the end so a
        crash mid-creation doesn't leave behind a sandbox_id pointing at a
        container we never finished wiring up."""
        from app.application.errors.exceptions import SandboxUnavailableError

        sandbox_id = session.sandbox_id
        sandbox = None
        if sandbox_id:
            try:
                sandbox = await self._sandbox_cls.get(sandbox_id)
            except SandboxUnavailableError:
                # Old container is gone — spawn a fresh one rather than
                # propagating the error. Common after a long restart or
                # janitor reaping a stale per-session container.
                logger.info(
                    "Sandbox %s unreachable; spawning fresh container", sandbox_id,
                )
                session.sandbox_id = None
        if not sandbox:
            sandbox = await self._sandbox_cls.create()
            session.sandbox_id = sandbox.id
        browser = await sandbox.get_browser()
        if not browser:
            logger.error(f"Failed to get browser for Sandbox {session.sandbox_id}")
            raise RuntimeError(f"Failed to get browser for Sandbox {session.sandbox_id}")

        # Resolve project attachments + DB-backed skill overlays in parallel —
        # both are independent reads keyed off session.project_id and used
        # only by the runner we're about to construct. The skill snapshot
        # locks in: the agent tool path is sync and re-querying every turn
        # would block the loop.
        skill_overlays_enabled = (
            self._skill_repository is not None and self._skill_store is not None
        )
        load_project = (
            self._project_repository is not None and session.project_id is not None
        )

        async def _load_attachments():
            if not load_project:
                return []
            project = await self._project_repository.find_by_id_and_user_id(
                session.project_id, session.user_id
            )
            return list(project.attachments) if project else []

        async def _load_global_skills():
            if not skill_overlays_enabled:
                return []
            return await self._skill_store.list_for_project(None)

        async def _load_project_skills():
            if not skill_overlays_enabled or not session.project_id:
                return []
            return await self._skill_store.list_for_project(session.project_id)

        project_attachments, global_overrides, project_overrides = await asyncio.gather(
            _load_attachments(), _load_global_skills(), _load_project_skills(),
        )

        skill_repository = self._skill_repository
        if skill_overlays_enabled and (global_overrides or project_overrides):
            skill_repository = LayeredSkillRepository(
                base=skill_repository,
                global_overrides=global_overrides,
                project_overrides=project_overrides,
            )

        task_runner = AgentTaskRunner(
            session_id=session.id,
            agent_id=session.agent_id,
            user_id=session.user_id,
            sandbox=sandbox,
            browser=browser,
            file_storage=self._file_storage,
            search_engine=self._search_engine,
            session_repository=self._session_repository,
            agent_repository=self._repository,
            mcp_repository=self._mcp_repository,
            plan_repository=self._plan_repository,
            extra_system_prompt=session.system_prompt,
            project_attachments=project_attachments,
            project_repository=self._project_repository,
            project_id=session.project_id,
            skill_repository=skill_repository,
        )

        task = self._task_cls.create(task_runner)
        session.task_id = task.id
        await self._session_repository.save(session)
        return task
        
    async def _get_task(self, session: Session) -> Optional[Task]:
        """Get a task for the given session"""

        task_id = session.task_id
        if not task_id:
            return None
        
        return self._task_cls.get(task_id)

    async def resume_in_flight(self, session_id: str) -> bool:
        """Best-effort restart of a session whose previous backend process
        died mid-task (dev-mode reload, k8s rollout, OOM, ...).

        Re-creates the task runner (which reattaches to the per-session
        sandbox) and re-enqueues the user's last message so the agent
        picks up where it left off without the user re-typing. Returns
        True on success, False if we should fall back to the WAITING
        state (user must send a fresh message)."""
        session = await self._session_repository.find_by_id(session_id)
        if not session:
            return False
        last_user = await self._session_repository.find_last_user_message(session_id)
        if last_user is None:
            return False
        # Old task_id points at a now-dead InMemoryTask in a registry that
        # didn't survive the restart; force a fresh runner.
        session.task_id = None
        try:
            task = await self._create_task(session)
        except Exception:
            logger.exception("Auto-resume failed for session %s", session_id)
            return False
        await task.input_stream.put(last_user.model_dump_json())
        await task.run()
        await self._session_repository.update_status(session_id, SessionStatus.RUNNING)
        return True

    async def stop_session(self, session_id: str) -> None:
        """Stop a session"""
        session = await self._session_repository.find_by_id(session_id)
        if not session:
            logger.error(f"Attempted to stop non-existent Session {session_id}")
            raise NotFoundError("Session not found")
        task = await self._get_task(session)
        if task:
            task.cancel()
        await self._session_repository.update_status(session_id, SessionStatus.COMPLETED)

    async def chat(
        self,
        session_id: str,
        user_id: str,
        message: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        latest_event_id: Optional[str] = None,
        attachments: Optional[List[dict]] = None
    ) -> AsyncGenerator[BaseEvent, None]:
        """
        Chat with an agent
        """

        try:
            session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
            if not session:
                logger.error(f"Attempted to chat with non-existent Session {session_id} for user {user_id}")
                raise NotFoundError("Session not found")

            task = await self._get_task(session)

            if message:
                if session.status != SessionStatus.RUNNING:
                    # Serialize task creation per-session so concurrent
                    # callers don't each spawn a sandbox.
                    lock = self._task_creation_lock(session_id)
                    try:
                        async with lock:
                            # Re-fetch under lock — another caller may have
                            # finished `_create_task` while we were waiting.
                            session = await self._session_repository.find_by_id_and_user_id(
                                session_id, user_id
                            )
                            if not session:
                                raise NotFoundError("Session not found")
                            task = await self._get_task(session)
                            if task is None or session.status != SessionStatus.RUNNING:
                                task = await self._create_task(session)
                    finally:
                        # Drop the lock as soon as nobody else is waiting on
                        # it, so the dict doesn't grow forever in long-lived
                        # backends. Safe because subsequent callers will just
                        # create a fresh lock — they're independent runs.
                        if not lock.locked():
                            self._task_creation_locks.pop(session_id, None)
                    if not task:
                        raise RuntimeError("Failed to create task")
                    # New task → fresh per-task output_stream whose IDs start
                    # at "00...01". The FE's latest_event_id (carried over from
                    # the prior task) would filter every new event out — reset.
                    latest_event_id = None

                await self._session_repository.update_latest_message(session_id, message, timestamp or datetime.now())

                message_event = MessageEvent(
                    message=message, 
                    role="user", 
                    attachments=[FileInfo(file_id=attachment["file_id"], filename=attachment["filename"]) for attachment in attachments] if attachments else None
                )

                event_id = await task.input_stream.put(message_event.model_dump_json())

                message_event.id = event_id
                await self._session_repository.add_event(session_id, message_event)
                
                await task.run()
                logger.debug(f"Put message into Session {session_id}'s event queue: {message[:50]}...")
            
            logger.info(f"Session {session_id} started")
            logger.debug(f"Session {session_id} task: {task}")
           
            while task and not task.done:
                event_id, event_str = await task.output_stream.get(start_id=latest_event_id, block_ms=0)
                latest_event_id = event_id
                if event_str is None:
                    logger.debug(f"No event found in Session {session_id}'s event queue")
                    continue
                event = TypeAdapter(AgentEvent).validate_json(event_str)
                event.id = event_id
                logger.debug(f"Got event from Session {session_id}'s event queue: {type(event).__name__}")
                await self._session_repository.update_unread_message_count(session_id, 0)
                yield event
                if isinstance(event, (DoneEvent, ErrorEvent, WaitEvent)):
                    break
            
            logger.info(f"Session {session_id} completed")

        except Exception as e:
            logger.exception(f"Error in Session {session_id}")
            event = ErrorEvent(error=str(e))
            await self._session_repository.add_event(session_id, event)
            yield event # TODO: raise api exception
        finally:
            await self._session_repository.update_unread_message_count(session_id, 0)