from typing import AsyncGenerator, Optional, List
import logging
from datetime import datetime
from app.application.errors.exceptions import NotFoundError, SandboxUnavailableError
from app.domain.models.session import ContextFile, Session, SessionSummary
from app.domain.repositories.session_repository import SessionRepository

from app.interfaces.schemas.session import ShellViewResponse
from app.interfaces.schemas.file import FileViewResponse
from app.domain.models.agent import Agent
from app.domain.services.agent_domain_service import AgentDomainService
from app.domain.models.event import AgentEvent
from typing import Type
from app.domain.models.agent import Agent
from app.application.services.sandbox_registry import SandboxRegistry
from app.domain.external.sandbox import Sandbox
from app.domain.external.search import SearchEngine
from app.domain.external.file import FileStorage
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.external.task import Task
from app.domain.models.file import FileInfo
from app.core.config import get_settings
from app.domain.repositories.mcp_repository import MCPRepository
from app.domain.repositories.plan_repository import PlanRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.skill_repository import SkillRepository, SkillStore
from app.domain.models.session import SessionStatus

# Set up logger
logger = logging.getLogger(__name__)

class AgentService:
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
        sandbox_registry: Optional[SandboxRegistry] = None,
    ):
        logger.info("Initializing AgentService")
        self._agent_repository = agent_repository
        self._session_repository = session_repository
        self._file_storage = file_storage
        self._plan_repository = plan_repository
        self._project_repository = project_repository
        # Single owner of sandbox lifecycle. See sandbox_registry.py for
        # the why. Falls back to a fresh registry if the caller didn't
        # wire one (test paths) — but in production both this service
        # and the domain service must share the same instance, otherwise
        # they have separate caches and locks and the dedup is gone.
        self._sandbox_registry = sandbox_registry or SandboxRegistry(
            sandbox_cls, session_repository,
        )
        self._agent_domain_service = AgentDomainService(
            self._agent_repository,
            self._session_repository,
            sandbox_cls,
            task_cls,
            file_storage,
            mcp_repository,
            plan_repository=plan_repository,
            search_engine=search_engine,
            project_repository=project_repository,
            skill_repository=skill_repository,
            skill_store=skill_store,
            sandbox_registry=self._sandbox_registry,
        )
        self._search_engine = search_engine
        self._sandbox_cls = sandbox_cls
    
    async def create_session(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Session:
        logger.info(
            f"Creating new session for user: {user_id} project: {project_id}"
        )
        agent = await self._create_agent()
        session = Session(
            agent_id=agent.id,
            user_id=user_id,
            project_id=project_id,
            system_prompt=system_prompt,
        )
        logger.info(f"Created new Session with ID: {session.id} for user: {user_id}")
        await self._session_repository.save(session)
        return session

    async def move_session_to_project(
        self, session_id: str, user_id: str, project_id: Optional[str]
    ) -> None:
        """Reassign a session to another project (or NULL to ungroup)."""
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            raise NotFoundError("Session not found")
        await self._session_repository.update_project_id(session_id, project_id)

    async def fork_from_plan(
        self, plan_id: str, user_id: str, target_project_id: Optional[str] = None,
    ) -> Session:
        """Branch a session from a specific plan's snapshot.

        Project files are copied (excluding heavy build artifacts) and a
        fresh git branch is checked out from the plan's tag, with two-way
        remotes wired up so a future merge-back can `git fetch` either
        side without manual setup.

        `target_project_id` controls workspace placement. The route layer
        creates a fresh project for forks so the sidebar (1 project = 1
        visible session) shows the original AND the fork as siblings;
        passing the parent's project_id would let the fork displace the
        parent in the sidebar.
        """
        from pathlib import Path

        from app.infrastructure.external.git.plan_versioning import fork_project

        plan = await self._plan_repository.find_plan(plan_id)
        if not plan:
            raise NotFoundError("Plan not found")
        if not plan.commit_sha:
            raise ValueError(
                "Plan has no committed snapshot — only completed plans "
                "with file changes can be forked."
            )

        parent = await self._session_repository.find_by_id_and_user_id(
            plan.session_id, user_id,
        )
        if not parent:
            raise NotFoundError("Parent session not found")

        agent = await self._create_agent()
        new_session = Session(
            agent_id=agent.id,
            user_id=user_id,
            project_id=target_project_id if target_project_id is not None else parent.project_id,
            system_prompt=parent.system_prompt,
            title=f"Fork: {plan.title or plan.goal or 'plan'}"[:120],
        )

        host_root = get_settings().sandbox_data_host_root
        src = Path(host_root) / parent.id / "project"
        dst = Path(host_root) / new_session.id / "project"
        branch = f"fork/{new_session.id[:12]}"

        ok = await fork_project(src, dst, plan_id, branch)
        if not ok:
            raise RuntimeError(
                "Failed to fork project files — see backend logs"
            )

        await self._session_repository.save(new_session)

        # Spawn the sandbox in the background so the fork API returns
        # immediately — sandbox creation takes 3-5s (docker container
        # spin-up + supervisord boot), too long for an interactive
        # button click. The supervisord-managed dev_server inside the
        # sandbox brings up vite on its own once the container's alive,
        # and PreviewToolView's auto-poll catches the URL the moment
        # the dev server is reachable.
        import asyncio as _asyncio

        async def _spawn_sandbox_bg() -> None:
            try:
                # Through the registry so concurrent recreate paths
                # (e.g. user immediately sends a chat message before
                # this background task finishes) dedup on the per-session
                # lock instead of double-spawning containers.
                await self._sandbox_registry.ensure_for(new_session)
            except Exception:
                logger.exception(
                    "Background sandbox create failed for forked session %s; "
                    "user can recover by sending a chat message",
                    new_session.id,
                )

        _asyncio.create_task(_spawn_sandbox_bg())

        logger.info(
            "Forked session %s from %s @ plan %s (branch %s) — sandbox spawning",
            new_session.id, parent.id, plan_id, branch,
        )
        return new_session

    async def _create_agent(self) -> Agent:
        logger.info("Creating new agent")
        settings = get_settings()
        agent = Agent(
            model_name=settings.model_name,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )
        logger.info(f"Created new Agent with ID: {agent.id}")
        
        # Save agent to repository
        await self._agent_repository.save(agent)
        logger.info(f"Saved agent {agent.id} to repository")
        
        logger.info(f"Agent created successfully with ID: {agent.id}")
        return agent

    async def regenerate_from_message(
        self,
        session_id: str,
        user_id: str,
        from_event_id: str,
        message: str,
        attachments: Optional[List[dict]] = None,
    ) -> None:
        """Truncate the session at `from_event_id`, then resume chat with `message`.

        Cancels any in-flight task first; the SSE stream the caller starts
        afterwards will pick up the new run.
        """
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            raise NotFoundError("Session not found")
        # Stop in-flight work so the new message doesn't fight the old run.
        try:
            await self._agent_domain_service.stop_session(session_id)
        except Exception:
            logger.exception("stop_session before regenerate failed; continuing")
        deleted = await self._session_repository.truncate_events_from(
            session_id, from_event_id
        )
        logger.info(
            "Regenerate %s: truncated %d events from %s", session_id, deleted, from_event_id
        )

    async def chat(
        self,
        session_id: str,
        user_id: str,
        message: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        event_id: Optional[str] = None,
        attachments: Optional[List[dict]] = None
    ) -> AsyncGenerator[AgentEvent, None]:
        logger.info(
            f"Starting chat with session {session_id}: {(message or '')[:50]}..."
        )
        # Directly use the domain service's chat method, which will check if the session exists
        async for event in self._agent_domain_service.chat(session_id, user_id, message, timestamp, event_id, attachments):
            logger.debug(f"Received event: {event}")
            yield event
        logger.info(f"Chat with session {session_id} completed")
    
    async def get_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        events_limit: Optional[int] = None,
        events_before: Optional[str] = None,
    ) -> Optional[Session]:
        """Get a session by ID, ensuring it belongs to the user.

        When `events_limit` is provided, returns only the latest N events
        (or the N immediately before `events_before` if a cursor is given).
        Used by the chat page to bound the initial network payload — long
        sessions previously shipped every event back at once."""
        logger.info(f"Getting session {session_id} for user {user_id}")
        if not user_id:
            session = await self._session_repository.find_by_id(session_id)
        else:
            session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            return None

        if events_limit is not None:
            # Replace the eagerly-loaded events with a paginated slice.
            # Repo orders ascending; we keep that ordering for the FE so
            # event replay walks chronologically without sorting upfront.
            session.events = await self._session_repository.find_events(
                session_id,
                before_id=events_before,
                limit=int(events_limit),
            )
        return session
    
    async def get_all_sessions(self, user_id: str) -> List[SessionSummary]:
        """Get all sessions for a specific user (lightweight summaries)"""
        logger.info(f"Getting all sessions for user {user_id}")
        return await self._session_repository.find_summaries_by_user_id(user_id)

    async def search_sessions(
        self, user_id: str, query: str, limit: int = 50
    ) -> List[SessionSummary]:
        query = query.strip()
        if not query:
            return []
        return await self._session_repository.search_summaries(user_id, query, limit)

    async def _cleanup_session_resources(
        self, session_id: str, sandbox_id: Optional[str]
    ) -> None:
        """Best-effort: stop+remove the sandbox container and wipe the
        host bind-mount dir. Failures are logged, not raised — the DB
        delete must still proceed so the user's UI stays consistent."""
        import asyncio
        import shutil
        from pathlib import Path

        if sandbox_id:
            try:
                sandbox = await self._sandbox_registry.fetch_unmanaged(sandbox_id)
                await sandbox.destroy()
                logger.info(
                    "Destroyed sandbox %s for session %s", sandbox_id, session_id,
                )
            except SandboxUnavailableError:
                # Container already gone (reaper, manual stop, never
                # spawned). Nothing to destroy — proceed to fs cleanup.
                logger.info(
                    "Sandbox %s already gone for session %s",
                    sandbox_id, session_id,
                )
            except Exception:
                logger.exception(
                    "Sandbox destroy failed for session %s (sandbox %s)",
                    session_id, sandbox_id,
                )
            finally:
                self._sandbox_registry.invalidate(sandbox_id)

        # Wipe the bind-mount root for this session — both `project/` (the
        # workspace) and any sibling files (logs, etc.) the sandbox image
        # might have written under <session_id>/.
        host_dir = Path(get_settings().sandbox_data_host_root) / session_id
        if host_dir.exists():
            try:
                await asyncio.to_thread(shutil.rmtree, host_dir)
                logger.info("Removed bind-mount dir %s", host_dir)
            except Exception:
                logger.exception("Failed to rmtree %s", host_dir)

    async def delete_session(self, session_id: str, user_id: str) -> None:
        """Delete a session and free its sandbox + disk resources."""
        logger.info(f"Deleting session {session_id} for user {user_id}")
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise NotFoundError("Session not found")

        await self._cleanup_session_resources(session_id, session.sandbox_id)
        await self._session_repository.delete(session_id)
        logger.info(f"Session {session_id} deleted successfully")

    async def merge_two_sessions(
        self, session_a_id: str, session_b_id: str, user_id: str,
    ) -> dict:
        """Merge one session's branch into another session's working tree.

        Direction inference: if exactly one of the two is on a `fork/*`
        branch, that's the source and the other is target. Otherwise
        raises ValueError — caller should ask the user to disambiguate.

        On clean merge or LLM-resolved merge, persists a synthetic Plan
        row on the target session (status=COMPLETED, tagged commit_sha
        set) so the result shows up in the FE's plan history with
        diff/restore/version bar. On unresolved conflict, the working
        tree is left mid-merge — caller can surface the file list to
        the user, who can finish in the agent's shell.

        Returns a dict shaped for direct API serialization:
        {status, target_session_id, source_session_id, commit_sha?,
         resolved_files, unresolved_files, error?}.
        """
        from pathlib import Path

        from app.domain.models.plan import PlanStatus, TaskInput
        from app.infrastructure.external.git.merge import (
            detect_branch,
            merge_session_with_resolve,
        )
        from app.infrastructure.external.git.plan_versioning import (
            init_repo_if_needed,
        )

        if session_a_id == session_b_id:
            raise ValueError("Cannot merge a session with itself")

        sess_a = await self._session_repository.find_by_id_and_user_id(
            session_a_id, user_id,
        )
        sess_b = await self._session_repository.find_by_id_and_user_id(
            session_b_id, user_id,
        )
        if not sess_a or not sess_b:
            raise NotFoundError("One or both sessions not found")

        host_root = get_settings().sandbox_data_host_root
        path_a = Path(host_root) / session_a_id / "project"
        path_b = Path(host_root) / session_b_id / "project"

        if not (path_a / ".git").exists() or not (path_b / ".git").exists():
            raise ValueError(
                "Both sessions must have a versioned project (auto-commit "
                "kicks in on the first plan completion).",
            )

        branch_a = await detect_branch(path_a)
        branch_b = await detect_branch(path_b)

        a_is_fork = branch_a.startswith("fork/")
        b_is_fork = branch_b.startswith("fork/")
        if a_is_fork == b_is_fork:
            raise ValueError(
                f"Cannot infer merge direction (both on '{'fork' if a_is_fork else 'main'}' "
                "branches). Future: add explicit target picker.",
            )

        if a_is_fork:
            source_id, source_path, source_branch = session_a_id, path_a, branch_a
            target_id, target_path, target_session = (
                session_b_id, path_b, sess_b,
            )
        else:
            source_id, source_path, source_branch = session_b_id, path_b, branch_b
            target_id, target_path, target_session = (
                session_a_id, path_a, sess_a,
            )

        # Surface the latest plan titles on each side as merge context for
        # the LLM resolver — much better than generic "main vs fork"
        # framing when conflicts hit.
        target_plans = await self._plan_repository.list_plans(target_id)
        source_plans = await self._plan_repository.list_plans(source_id)
        target_summary = (
            (target_plans[0].title or target_plans[0].goal or "").strip()
            if target_plans else ""
        ) or "main"
        source_summary = (
            (source_plans[0].title or source_plans[0].goal or "").strip()
            if source_plans else ""
        ) or f"branch {source_branch}"

        # Pre-create a Plan row so the tag we may set later refers to a
        # known plan_id. We mark it COMPLETED + set commit_sha only after
        # a successful merge; on failure we delete or leave it pending.
        plan = await self._plan_repository.create_with_tasks(
            session_id=target_id,
            title=f"Merge fork: {source_summary}"[:120],
            goal=f"Merge {source_branch} into {await detect_branch(target_path)}",
            language=None,
            tasks=[TaskInput(title=f"Merge {source_branch}")],
        )
        # Suppress unused-name warning — keep target_session bound in case
        # we want it for richer summaries later.
        _ = target_session

        await init_repo_if_needed(target_path)

        result = await merge_session_with_resolve(
            target_path=target_path,
            source_session_id=source_id,
            source_branch=source_branch,
            target_summary=target_summary,
            source_summary=source_summary,
            plan_id_for_tag=plan.id,
        )

        if result.status in ("merged", "resolved", "noop"):
            # Mark plan completed; set commit_sha for non-noop results.
            await self._plan_repository.update_plan_status(
                plan.id, PlanStatus.COMPLETED,
            )
            if result.commit_sha:
                await self._plan_repository.set_commit_sha(
                    plan.id, result.commit_sha,
                )
            logger.info(
                "Merged session %s into %s: status=%s commit=%s "
                "(resolved=%s, unresolved=%s)",
                source_id, target_id, result.status, result.commit_sha,
                result.resolved_files, result.unresolved_files,
            )

            # Consume the source: drop the dead remote, then remove the
            # source session + (if it had its own project) the project.
            # Same outcome as if the user had clicked Delete on the fork
            # in the sidebar — sandbox container gone, bind mount wiped,
            # DB rows cascaded.
            from app.infrastructure.external.git.plan_versioning import _run_git
            from app.infrastructure.external.git.merge import _fork_remote_name
            try:
                await _run_git(
                    target_path,
                    "remote", "remove", _fork_remote_name(source_id),
                    check=False,
                )
            except Exception:
                logger.exception("merge: drop fork remote failed")

            try:
                # Build source session ref again (it might be either A or B).
                source_session = sess_a if source_id == session_a_id else sess_b
                source_project_id = source_session.project_id
                # Wipe sandbox + bind mount.
                await self._cleanup_session_resources(
                    source_id, source_session.sandbox_id,
                )
                # Drop the session row (cascades plans + tasks + events).
                await self._session_repository.delete(source_id)
                # If the fork had its own project (and it's different from
                # the target's), drop the empty project row too.
                target_project_id = (
                    sess_a.project_id if target_id == session_a_id
                    else sess_b.project_id
                )
                if (
                    source_project_id
                    and source_project_id != target_project_id
                    and self._project_repository is not None
                ):
                    await self._project_repository.delete(
                        source_project_id, user_id,
                    )
                logger.info(
                    "Consumed source session %s after merge into %s",
                    source_id, target_id,
                )
            except Exception:
                logger.exception(
                    "Post-merge cleanup of source session %s failed", source_id,
                )
        else:
            await self._plan_repository.update_plan_status(
                plan.id, PlanStatus.FAILED,
                error=result.error or "merge had unresolved conflicts",
            )
            logger.warning(
                "Merge failed: %s -> %s: status=%s error=%s",
                source_id, target_id, result.status, result.error,
            )

        return {
            "status": result.status,
            "target_session_id": target_id,
            "source_session_id": source_id,
            "commit_sha": result.commit_sha,
            "resolved_files": result.resolved_files,
            "unresolved_files": result.unresolved_files,
            "error": result.error,
            "plan_id": plan.id,
        }

    async def cleanup_project_session_resources(
        self, project_id: str, user_id: str
    ) -> None:
        """Free sandbox + disk for every session under a project. Called
        before `project_service.delete_project` so the bulk DB delete
        doesn't strand running containers and on-disk bind mounts.
        Idempotent and best-effort."""
        sessions = await self._session_repository.find_ids_and_sandbox_by_project_id(
            project_id, user_id,
        )
        for session_id, sandbox_id in sessions:
            await self._cleanup_session_resources(session_id, sandbox_id)

    async def stop_session(self, session_id: str, user_id: str) -> None:
        """Stop a session, ensuring it belongs to the user"""
        logger.info(f"Stopping session {session_id} for user {user_id}")
        # First verify the session belongs to the user
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise NotFoundError("Session not found")
        await self._agent_domain_service.stop_session(session_id)
        logger.info(f"Session {session_id} stopped successfully")

    async def clear_unread_message_count(self, session_id: str, user_id: str) -> None:
        """Clear the unread message count for a session, ensuring it belongs to the user"""
        logger.info(f"Clearing unread message count for session {session_id} for user {user_id}")
        await self._session_repository.update_unread_message_count(session_id, 0)
        logger.info(f"Unread message count cleared for session {session_id}")

    async def shutdown(self):
        logger.info("Closing all agents and cleaning up resources")
        # Clean up all Agents and their associated sandboxes
        await self._agent_domain_service.shutdown()
        logger.info("All agents closed successfully")

    async def _resolve_or_recreate_sandbox(self, session: Session) -> Sandbox:
        """Thin shim over `SandboxRegistry.ensure_for`. Kept as a method
        so the file_view / vnc / shell handlers below read clearly; all
        the lifecycle logic (per-session locking, dead-container
        detection, respawn) lives in the registry.
        """
        return await self._sandbox_registry.ensure_for(session)

    async def shell_view(self, session_id: str, shell_session_id: str, user_id: str) -> ShellViewResponse:
        """View shell session output, ensuring session belongs to the user"""
        logger.info(f"Getting shell view for session {session_id} for user {user_id}")
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise NotFoundError("Session not found")
        
        if not session.sandbox_id:
            raise RuntimeError("Session has no sandbox environment")
        
        sandbox = await self._sandbox_registry.ensure_for(session)
        result = await sandbox.view_shell(shell_session_id, console=True)
        if result.success:
            return ShellViewResponse(**result.data)
        else:
            raise RuntimeError(f"Failed to get shell output: {result.message}")

    async def get_preview_url(self, session_id: str) -> Optional[str]:
        """Return the `http://localhost:<port>` preview URL for the
        session's dev server, or None if it's not actually reachable.

        Pure read — `lookup_alive` doesn't spawn. The iframe polls this
        endpoint while warming up; if we created on poll we'd race with
        chat-warmup's create. The flow is:

          1. Registry verifies the bound container is alive (cache or
             docker inspect). If it's gone the cache is dropped and we
             return None — user gets "no preview yet"; whichever route
             actively wants a sandbox (chat, file_view, vnc) will
             respawn through `ensure_for_session`.
          2. HEAD-probe the sandbox's *internal* URL (docker-network
             IP, container port 5173). Backend's own `localhost` is
             itself, so probing `localhost:<host_port>` from here
             always fails even when vite is up; the user's browser
             reaches that same host port directly because the iframe
             runs on the host.
          3. If probe fails, drop the cache entry — could be vite
             crashed even though container is alive (supervisord will
             restart it; next poll picks it up) or container died
             between the registry's last check and now.
        """
        import httpx

        logger.info(f"Getting preview URL for session {session_id}")
        sandbox = await self._sandbox_registry.lookup_alive(session_id)
        if sandbox is None:
            return None

        url = getattr(sandbox, "preview_url", None)
        if not url:
            return None

        probe_url = getattr(sandbox, "preview_internal_url", None) or url
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                r = await client.head(probe_url)
                if r.status_code >= 500:
                    return None
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
            logger.info(
                "Preview probe: session %s url %s unreachable (%s)",
                session_id, probe_url, type(e).__name__,
            )
            self._sandbox_registry.invalidate(sandbox.id)
            return None
        return url

    async def get_vnc_url(self, session_id: str) -> str:
        """Get VNC URL for a session, ensuring it belongs to the user.

        Auto-recreates the sandbox if the previously-bound container is
        gone — the user reopened an old session whose sandbox died and
        we'd rather just give them a working VNC than make them send a
        chat message just to wake the panel.
        """
        logger.info(f"Getting VNC URL for session {session_id}")

        session = await self._session_repository.find_by_id(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            raise NotFoundError("Session not found")

        sandbox = await self._resolve_or_recreate_sandbox(session)
        return sandbox.vnc_url

    async def get_shell_stream_url(
        self,
        session_id: str,
        cols: int = 80,
        rows: int = 24,
        cwd: Optional[str] = None,
    ) -> str:
        """Return the sandbox-side WS URL for the interactive pty shell.

        Used by the chat UI's xterm.js terminal. Auth is up to the caller —
        the WS route does its own session-ownership check + signed URL
        verification."""
        logger.info(f"Getting shell stream URL for session {session_id}")
        session = await self._session_repository.find_by_id(session_id)
        if not session:
            raise NotFoundError("Session not found")
        sandbox = await self._resolve_or_recreate_sandbox(session)
        base = sandbox.shell_stream_url
        params = []
        if cols > 0:
            params.append(f"cols={int(cols)}")
        if rows > 0:
            params.append(f"rows={int(rows)}")
        if cwd:
            from urllib.parse import quote
            params.append(f"cwd={quote(cwd, safe='/')}")
        return f"{base}?{'&'.join(params)}" if params else base

    async def file_view(self, session_id: str, file_path: str, user_id: str) -> FileViewResponse:
        """View file content, ensuring session belongs to the user"""
        logger.info(f"Getting file view for session {session_id} for user {user_id}")
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise NotFoundError("Session not found")

        sandbox = await self._resolve_or_recreate_sandbox(session)
        result = await sandbox.file_read(file_path)
        if result.success:
            return FileViewResponse(**result.data)
        else:
            raise RuntimeError(f"Failed to read file: {result.message}")
    
    async def file_list(
        self,
        session_id: str,
        dir_path: str,
        user_id: str,
        show_hidden: bool = False,
    ) -> dict:
        """List one directory level inside a session's sandbox.

        Used by the FE explorer tree (lazy expand on click). Auth checks
        match file_view: session must belong to the user."""
        logger.info(f"Listing dir {dir_path!r} for session {session_id} user {user_id}")
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            raise NotFoundError("Session not found")
        sandbox = await self._resolve_or_recreate_sandbox(session)
        result = await sandbox.file_list(dir_path, show_hidden=show_hidden)
        if result.success:
            return result.data
        raise RuntimeError(f"Failed to list directory: {result.message}")

    async def is_session_shared(self, session_id: str) -> bool:
        """Check if a session is shared"""
        logger.info(f"Checking if session {session_id} is shared")
        session = await self._session_repository.find_by_id(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            raise NotFoundError("Session not found")
        return session.is_shared

    async def get_session_files(self, session_id: str, user_id: Optional[str] = None) -> List[FileInfo]:
        """Get files for a session, ensuring it belongs to the user"""
        logger.info(f"Getting files for session {session_id} for user {user_id}")
        session = await self.get_session(session_id, user_id)
        return session.files

    # Hard caps on context-file storage. Picked to keep `extra_system_prompt`
    # under ~1 MB per turn — Claude's prompt cache works best below that and
    # users uploading multi-megabyte specs probably want a retrieval tool, not
    # the full corpus on every turn (will be the next iteration).
    _CONTEXT_FILE_MAX_SIZE = 256 * 1024  # 256 KB per file
    _CONTEXT_FILES_MAX_COUNT = 20
    _CONTEXT_FILES_MAX_TOTAL_SIZE = 2 * 1024 * 1024  # 2 MB per session

    async def list_context_files(
        self, session_id: str, user_id: str,
    ) -> List[ContextFile]:
        """All Markdown reference docs attached to this session."""
        session = await self._session_repository.find_by_id_and_user_id(
            session_id, user_id,
        )
        if not session:
            raise NotFoundError("Session not found")
        return await self._session_repository.list_context_files(session_id)

    async def add_context_file(
        self, session_id: str, user_id: str, filename: str, content: str,
    ) -> ContextFile:
        """Attach a Markdown doc. Validates size + per-session count, then
        delegates the write. Caller must already have authorized via
        `find_by_id_and_user_id`."""
        session = await self._session_repository.find_by_id_and_user_id(
            session_id, user_id,
        )
        if not session:
            raise NotFoundError("Session not found")

        filename = filename.strip()
        if not filename:
            raise ValueError("filename is required")
        size = len(content.encode("utf-8"))
        if size == 0:
            raise ValueError("file is empty")
        if size > self._CONTEXT_FILE_MAX_SIZE:
            raise ValueError(
                f"file too large ({size} bytes; max "
                f"{self._CONTEXT_FILE_MAX_SIZE})"
            )

        existing = await self._session_repository.list_context_files(session_id)
        if len(existing) >= self._CONTEXT_FILES_MAX_COUNT:
            raise ValueError(
                f"too many context files (max "
                f"{self._CONTEXT_FILES_MAX_COUNT})"
            )
        total_size = sum(cf.size for cf in existing) + size
        if total_size > self._CONTEXT_FILES_MAX_TOTAL_SIZE:
            raise ValueError(
                f"context files total size exceeded "
                f"({total_size} > {self._CONTEXT_FILES_MAX_TOTAL_SIZE})"
            )

        cf = ContextFile(filename=filename, content=content, size=size)
        await self._session_repository.add_context_file(session_id, cf)
        logger.info(
            "Attached context file %s (%d bytes) to session %s",
            filename, size, session_id,
        )
        return cf

    async def remove_context_file(
        self, session_id: str, user_id: str, file_id: str,
    ) -> None:
        """Detach a context file. 404 if either the session or file
        doesn't exist or doesn't belong to the user."""
        session = await self._session_repository.find_by_id_and_user_id(
            session_id, user_id,
        )
        if not session:
            raise NotFoundError("Session not found")
        ok = await self._session_repository.remove_context_file(
            session_id, file_id,
        )
        if not ok:
            raise NotFoundError("Context file not found")
    
    async def get_shared_session_files(self, session_id: str) -> List[FileInfo]:
        """Get files for a shared session"""
        logger.info(f"Getting files for shared session {session_id}")
        session = await self._session_repository.find_by_id(session_id)
        if not session or not session.is_shared:
            logger.error(f"Shared session {session_id} not found or not shared")
            raise NotFoundError("Session not found")
        return session.files

    async def share_session(self, session_id: str, user_id: str) -> None:
        """Share a session, ensuring it belongs to the user"""
        logger.info(f"Sharing session {session_id} for user {user_id}")
        # First verify the session belongs to the user
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise NotFoundError("Session not found")
        
        await self._session_repository.update_shared_status(session_id, True)
        logger.info(f"Session {session_id} shared successfully")

    async def unshare_session(self, session_id: str, user_id: str) -> None:
        """Unshare a session, ensuring it belongs to the user"""
        logger.info(f"Unsharing session {session_id} for user {user_id}")
        # First verify the session belongs to the user
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise NotFoundError("Session not found")
        
        await self._session_repository.update_shared_status(session_id, False)
        logger.info(f"Session {session_id} unshared successfully")

    async def get_shared_session(self, session_id: str) -> Optional[Session]:
        """Get a shared session by ID (no user authentication required)"""
        logger.info(f"Getting shared session {session_id}")
        session = await self._session_repository.find_by_id(session_id)
        if not session or not session.is_shared:
            logger.error(f"Shared session {session_id} not found or not shared")
            return None
        return session