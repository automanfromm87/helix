from typing import Any, Dict, Optional, AsyncGenerator, List
import asyncio
import base64
import logging
from pydantic import TypeAdapter
from app.domain.models.message import Message
from app.domain.models.event import (
    BaseEvent,
    ErrorEvent,
    TitleEvent,
    MessageEvent,
    DoneEvent,
    ToolEvent,
    WaitEvent,
    FileToolContent,
    ShellToolContent,
    SearchToolContent,
    BrowserToolContent,
    SkillToolContent,
    ToolContent,
    ToolStatus,
    AgentEvent,
    McpToolContent,
)
from app.application.errors.exceptions import SandboxUnavailableError
from app.domain.constants import SANDBOX_PROJECT_DIR
from app.domain.services.flows.plan_act import PlanActFlow
from app.domain.external.sandbox import Sandbox
from app.domain.external.browser import Browser
from app.domain.external.search import SearchEngine
from app.domain.external.file import FileStorage
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.external.task import TaskRunner, Task
from app.domain.repositories.session_repository import SessionRepository
from app.domain.repositories.mcp_repository import MCPRepository
from app.domain.repositories.plan_repository import PlanRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.models.session import SessionStatus
from app.domain.models.file import FileInfo
from app.domain.services.tools.mcp import MCPToolkit
from app.domain.models.tool_result import ToolResult, TOOL_RESULT_SANDBOX_UNAVAILABLE
from app.domain.models.search import SearchResults

logger = logging.getLogger(__name__)

class AgentTaskRunner(TaskRunner):
    """Agent task that can be cancelled"""
    def __init__(
        self,
        session_id: str,
        agent_id: str,
        user_id: str,
        sandbox: Sandbox,
        browser: Browser,
        agent_repository: AgentRepository,
        session_repository: SessionRepository,
        file_storage: FileStorage,
        mcp_repository: MCPRepository,
        plan_repository: PlanRepository,
        search_engine: Optional[SearchEngine] = None,
        extra_system_prompt: Optional[str] = None,
        project_attachments: Optional[List[FileInfo]] = None,
        project_repository: Optional[ProjectRepository] = None,
        project_id: Optional[str] = None,
        skill_repository=None,
        has_context_files: bool = False,
    ):
        self._session_id = session_id
        self._agent_id = agent_id
        self._user_id = user_id
        self._sandbox = sandbox
        self._browser = browser
        self._search_engine = search_engine
        self._repository = agent_repository
        self._session_repository = session_repository
        self._plan_repository = plan_repository
        self._file_storage = file_storage
        self._mcp_repository = mcp_repository
        self._mcp_tool = MCPToolkit()
        self._project_attachments: List[FileInfo] = project_attachments or []
        self._project_repository = project_repository
        self._project_id = project_id
        # Track the most recent assistant message text so we can fold it into
        # project shared memory once the session completes.
        self._last_assistant_message: Optional[str] = None
        self._last_title: Optional[str] = None
        self._flow = PlanActFlow(
            self._agent_id,
            self._repository,
            self._session_id,
            self._session_repository,
            self._plan_repository,
            self._sandbox,
            self._browser,
            self._mcp_tool,
            self._search_engine,
            extra_system_prompt=extra_system_prompt,
            skill_repository=skill_repository,
            has_context_files=has_context_files,
        )

    async def _put_and_add_event(self, task: Task, event: AgentEvent) -> None:
        event_id = await task.output_stream.put(event.model_dump_json())
        event.id = event_id
        await self._session_repository.add_event(self._session_id, event)
    
    async def _pop_event(self, task: Task) -> AgentEvent:
        event_id, event_str = await task.input_stream.pop()
        if event_str is None:
            logger.warning(f"Agent {self._agent_id} received empty message")
            return
        event = TypeAdapter(AgentEvent).validate_json(event_str)
        event.id = event_id
        return event
    
    async def _get_browser_screenshot(self) -> str:
        screenshot = await self._browser.screenshot()
        result = await self._file_storage.upload_file(screenshot, "screenshot.png", self._user_id)
        return result.file_id

    async def _sync_file_to_storage(self, file_path: str) -> Optional[FileInfo]:
        """Upload or update file and return FileInfo"""
        try:
            file_info = await self._session_repository.get_file_by_path(self._session_id, file_path)
            file_data = await self._sandbox.file_download(file_path)
            if file_info:
                await self._session_repository.remove_file(self._session_id, file_info.file_id)
            file_name = file_path.split("/")[-1]
            file_info = await self._file_storage.upload_file(file_data, file_name, self._user_id)
            file_info.file_path = file_path
            await self._session_repository.add_file(self._session_id, file_info)
            return file_info
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} failed to sync file: {e}")
    
    async def _sync_file_to_sandbox(self, file_id: str) -> Optional[FileInfo]:
        """Download file from storage to sandbox"""
        try:
            file_data, file_info = await self._file_storage.download_file(file_id, self._user_id)
            file_path = "/home/ubuntu/upload/" + file_info.filename
            result = await self._sandbox.file_upload(file_data, file_path)
            if result.success:
                file_info.file_path = file_path
                return file_info
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} failed to sync file: {e}")

    # Cap on rolled-up project memory — pure char count, not tokens. Roughly
    # ~6k tokens with the chars/4 heuristic.
    _SHARED_MEMORY_CHAR_BUDGET = 24_000

    async def _maybe_update_project_shared_memory(self) -> None:
        """Append a one-line summary of this session to its project's shared
        memory, so future sessions in the same project inherit the gist.
        """
        if not (self._project_repository and self._project_id):
            return
        if not self._last_assistant_message:
            return
        try:
            project = await self._project_repository.find_by_id_and_user_id(
                self._project_id, self._user_id
            )
            if not project:
                return
            # Single line per session; trim long ones so the budget stays sane.
            title = (self._last_title or "Untitled").strip()
            summary_line = self._last_assistant_message.strip().split("\n", 1)[0][:200]
            entry = f"- **{title}**: {summary_line}"
            existing = (project.shared_memory or "").strip()
            combined = f"{existing}\n{entry}".strip() if existing else entry
            # Keep newest entries; trim from the front if over budget.
            if len(combined) > self._SHARED_MEMORY_CHAR_BUDGET:
                combined = combined[-self._SHARED_MEMORY_CHAR_BUDGET:]
                # Snap to the next newline so we don't truncate mid-bullet.
                cut = combined.find("\n")
                if cut >= 0:
                    combined = combined[cut + 1:]
            await self._project_repository.update_shared_memory(
                self._project_id, self._user_id, combined
            )
        except Exception:
            # Memory consolidation is best-effort.
            logger.exception(
                "Failed to update project %s shared memory after session %s",
                self._project_id, self._session_id,
            )

    async def _sync_project_attachments(self) -> None:
        """Drop project-level attachments into the sandbox at /home/ubuntu/project/.

        Best-effort: a download / upload failure for one file shouldn't kill
        the run. Logged and skipped.
        """
        for attachment in self._project_attachments:
            try:
                file_data, info = await self._file_storage.download_file(
                    attachment.file_id, self._user_id
                )
                file_path = f"{SANDBOX_PROJECT_DIR}/{info.filename}"
                result = await self._sandbox.file_upload(file_data, file_path)
                if not result.success:
                    logger.warning(
                        "Project attachment %s failed sandbox upload: %s",
                        attachment.file_id, result,
                    )
            except Exception:
                logger.exception(
                    "Failed to sync project attachment %s into sandbox", attachment.file_id
                )

    async def _sync_message_attachments_to_storage(self, event: MessageEvent) -> None:
        """Sync message attachments and update event attachments"""
        attachments: List[FileInfo] = []
        try:
            if event.attachments:
                for attachment in event.attachments:
                    file_info = await self._sync_file_to_storage(attachment.file_path)
                    if file_info:
                        attachments.append(file_info)
            event.attachments = attachments
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} failed to sync attachments to storage: {e}")
    
    async def _sync_message_attachments_to_sandbox(self, event: MessageEvent) -> None:
        """Sync message attachments and update event attachments"""
        attachments: List[FileInfo] = []
        try:
            if event.attachments:
                for attachment in event.attachments:
                    file_info = await self._sync_file_to_sandbox(attachment.file_id)
                    if file_info:
                        attachments.append(file_info)
                        await self._session_repository.add_file(self._session_id, file_info)
            event.attachments = attachments
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} failed to sync attachments to event: {e}")

    # MIME types Anthropic vision accepts. Anything outside this list is
    # treated as a regular file attachment (sandbox-only) — sending the
    # bytes as an `image` block would just trip an API 400.
    _SUPPORTED_VISION_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    # Per-image inline cap. Claude allows up to ~5MB base64 per image; we
    # enforce a tighter raw-bytes ceiling so multiple images don't blow the
    # request payload. Above this, we skip vision and fall back to "file in
    # sandbox" semantics for the agent.
    _MAX_INLINE_IMAGE_BYTES = 4 * 1024 * 1024

    async def _build_image_blocks(self, event: MessageEvent) -> List[Dict[str, Any]]:
        """Materialize image attachments as Anthropic image content blocks.

        Re-downloads each image-MIME attachment from file_storage and
        base64-encodes it inline. Skipped silently if the file isn't an
        image, exceeds size cap, or fails to download — the agent still
        sees it as a regular file under /home/ubuntu/upload/."""
        blocks: List[Dict[str, Any]] = []
        if not event.attachments:
            return blocks
        for attachment in event.attachments:
            mime = (attachment.content_type or "").lower()
            if mime not in self._SUPPORTED_VISION_MIMES:
                continue
            if not attachment.file_id:
                continue
            try:
                file_data, _ = await self._file_storage.download_file(
                    attachment.file_id, self._user_id
                )
                raw = file_data.read() if hasattr(file_data, "read") else file_data
                if isinstance(raw, str):
                    raw = raw.encode()
                if len(raw) > self._MAX_INLINE_IMAGE_BYTES:
                    logger.info(
                        "Skipping vision for %s — %d bytes exceeds cap %d",
                        attachment.file_id, len(raw), self._MAX_INLINE_IMAGE_BYTES,
                    )
                    continue
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": base64.b64encode(raw).decode("ascii"),
                    },
                })
            except Exception:
                logger.exception(
                    "Failed to fetch image %s for vision content block",
                    attachment.file_id,
                )
        return blocks
    

    async def _handle_tool_event(self, event: ToolEvent):
        """Generate side-panel `tool_content` for an emitted ToolEvent.

        Dispatches to a per-tool renderer based on `event.tool_name`. Each
        renderer is its own small async method so the failure modes stay
        isolated — adding a new tool type means writing one renderer and
        registering it, instead of wedging another elif into a long chain.
        """
        if event.status != ToolStatus.CALLED:
            return
        # If the tool call itself reported sandbox-unavailable, the follow-
        # up sandbox calls below would just hit the same error. Skip
        # rendering — FE shows the args/error inline.
        fr = event.function_result
        if fr is not None and fr.code == TOOL_RESULT_SANDBOX_UNAVAILABLE:
            return

        renderer = self._TOOL_RENDERERS.get(event.tool_name)
        if renderer is None:
            logger.warning(
                "Agent %s received unknown tool event: %s",
                self._agent_id, event.tool_name,
            )
            return

        try:
            event.tool_content = await renderer(self, event)
        except SandboxUnavailableError as e:
            # Backing sandbox is offline (operator stopped it, container
            # disappeared, network blip). Skip the render — single INFO log
            # instead of a six-page traceback.
            logger.info(
                "Agent %s skipped tool render (sandbox unavailable): %s",
                self._agent_id, e,
            )
        except Exception:
            logger.exception(
                "Agent %s failed to generate tool content for %s",
                self._agent_id, event.tool_name,
            )

    # ------------------------------------------------------------------
    # Per-tool renderers
    # ------------------------------------------------------------------
    #
    # Each renderer takes `self` + a CALLED ToolEvent and returns an
    # Optional[ToolContent]. Returning None means "don't show a side panel
    # for this event" (e.g. failed browser nav has no usable screenshot).
    # All of them must defend against the patterns smaller models produce:
    # missing args keys, non-dict args, ToolResult.data being None,
    # tool_result success=False with no data attached.

    async def _render_browser(self, event: ToolEvent) -> Optional[ToolContent]:
        # Failed nav (blocked, target_closed) → browser may be on a
        # non-renderable page. Skip silently; FE renders the args.
        if event.function_result and not event.function_result.success:
            return None
        return BrowserToolContent(screenshot=await self._get_browser_screenshot())

    async def _render_search(self, event: ToolEvent) -> Optional[ToolContent]:
        fr: ToolResult[SearchResults] = event.function_result
        if fr and fr.success and fr.data:
            return SearchToolContent(results=fr.data.results)
        return SearchToolContent(results=[])

    async def _render_shell(self, event: ToolEvent) -> Optional[ToolContent]:
        args = event.function_args if isinstance(event.function_args, dict) else {}
        shell_id = args.get("id")
        if not shell_id:
            return ShellToolContent(console="(No Console)")
        result = await self._sandbox.view_shell(shell_id, console=True)
        if result and result.success and result.data:
            return ShellToolContent(console=result.data.get("console", []))
        msg = (result.message if result else None) or "no output"
        return ShellToolContent(console=f"(shell unavailable: {msg})")

    async def _render_file(self, event: ToolEvent) -> Optional[ToolContent]:
        args = event.function_args if isinstance(event.function_args, dict) else {}
        file_path = args.get("file")
        if not isinstance(file_path, str) or not file_path:
            return FileToolContent(content="(No Content)")
        result = await self._sandbox.file_read(file_path)
        if result and result.success and result.data:
            content = result.data.get("content", "")
            await self._sync_file_to_storage(file_path)
            return FileToolContent(content=content)
        msg = (result.message if result else None) or "read failed"
        return FileToolContent(content=f"(file unavailable: {msg})")

    async def _render_skill(self, event: ToolEvent) -> Optional[ToolContent]:
        # `load_skill` returns the skill body as a markdown string in
        # ToolResult.data. Defended against missing args["name"] /
        # non-string body.
        args = event.function_args if isinstance(event.function_args, dict) else {}
        raw_name = args.get("name")
        skill_name = raw_name if isinstance(raw_name, str) else ""
        fr = event.function_result
        if fr and fr.success and fr.data is not None:
            body = fr.data if isinstance(fr.data, str) else str(fr.data)
        elif fr and fr.message:
            body = f"_(skill load failed: {fr.message})_"
        else:
            body = "_(skill body unavailable)_"
        return SkillToolContent(name=skill_name, body=body)

    async def _render_mcp(self, event: ToolEvent) -> Optional[ToolContent]:
        fr = event.function_result
        if fr is None:
            return McpToolContent(result="No result available")
        if getattr(fr, "data", None):
            return McpToolContent(result=fr.data)
        if getattr(fr, "success", False):
            payload = fr.model_dump() if hasattr(fr, "model_dump") else str(fr)
            return McpToolContent(result=payload)
        return McpToolContent(result=str(fr))

    # Dispatch table: tool_name -> bound renderer. Class-level so the dict
    # is built once, not on every event. `_TOOL_RENDERERS` keys must match
    # the toolkit `name` attributes.
    _TOOL_RENDERERS = {
        "browser": _render_browser,
        "search": _render_search,
        "shell": _render_shell,
        "file": _render_file,
        "skill": _render_skill,
        "mcp": _render_mcp,
    }

    async def run(self, task: Task) -> None:
        """Process agent's message queue and run the agent's flow"""
        try:
            logger.info(f"Agent {self._agent_id} message processing task started")
            await self._sandbox.ensure_sandbox()
            await self._mcp_tool.initialized(await self._mcp_repository.get_mcp_config())
            # Drop project-level files into the sandbox once per task. Cheap if
            # the list is empty, and we only run this on task creation, not on
            # every message turn.
            await self._sync_project_attachments()
            while not await task.input_stream.is_empty():
                event = await self._pop_event(task)
                message = ""
                if isinstance(event, MessageEvent):
                    message = event.message or ""
                    await self._sync_message_attachments_to_sandbox(event)
                    
                logger.info(f"Agent {self._agent_id} received new message: {message[:50]}...")

                image_blocks = await self._build_image_blocks(event) if isinstance(event, MessageEvent) else []
                message_obj = Message(
                    message=message,
                    attachments=[attachment.file_path for attachment in event.attachments],
                    image_blocks=image_blocks,
                )
                
                async for event in self._run_flow(message_obj):
                    await self._put_and_add_event(task, event)
                    if isinstance(event, TitleEvent):
                        await self._session_repository.update_title(self._session_id, event.title)
                        self._last_title = event.title
                    elif isinstance(event, MessageEvent):
                        await self._session_repository.update_latest_message(self._session_id, event.message, event.timestamp)
                        await self._session_repository.increment_unread_message_count(self._session_id)
                        # Track only assistant turns — user role MessageEvents
                        # also flow through here on the input path.
                        if event.role != "user" and event.message:
                            self._last_assistant_message = event.message
                    elif isinstance(event, WaitEvent):
                        await self._session_repository.update_status(self._session_id, SessionStatus.WAITING)
                        return
                    if not await task.input_stream.is_empty():
                        break

            await self._session_repository.update_status(self._session_id, SessionStatus.COMPLETED)
            await self._maybe_update_project_shared_memory()
        except asyncio.CancelledError:
            logger.info(f"Agent {self._agent_id} task cancelled")
            await self._put_and_add_event(task, DoneEvent())
            await self._session_repository.update_status(self._session_id, SessionStatus.COMPLETED)
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} task encountered exception: {str(e)}")
            await self._put_and_add_event(task, ErrorEvent(error=f"Task error: {str(e)}"))
            # Mark INTERRUPTED (not COMPLETED) so a backend restart with the
            # underlying bug fixed can auto-resume the session. COMPLETED
            # would terminate the chat for good and require the user to
            # re-send the message manually.
            await self._session_repository.update_status(self._session_id, SessionStatus.INTERRUPTED)
    
    async def _run_flow(self, message: Message) -> AsyncGenerator[BaseEvent, None]:
        """Process a single message through the agent's flow and yield events"""
        if not message.message:
            logger.warning(f"Agent {self._agent_id} received empty message")
            yield ErrorEvent(error="No message")
            return

        async for event in self._flow.run(message):
            if isinstance(event, ToolEvent):
                # TODO: move to tool function
                await self._handle_tool_event(event)
            elif isinstance(event, MessageEvent):
                await self._sync_message_attachments_to_storage(event)
            yield event

        logger.info(f"Agent {self._agent_id} completed processing one message")

    
    async def on_done(self, task: Task) -> None:
        """Called when the task is done"""
        logger.info(f"Agent {self._agent_id} task done")


    async def destroy(self) -> None:
        """Destroy the task and release resources"""
        logger.info("Starting to destroy agent task")
        
        # Destroy sandbox environment
        if self._sandbox:
            logger.debug(f"Destroying Agent {self._agent_id}'s sandbox environment")
            await self._sandbox.destroy()
        
        if self._mcp_tool:
            logger.debug(f"Destroying Agent {self._agent_id}'s MCP tool")
            await self._mcp_tool.cleanup()
        
        logger.debug(f"Agent {self._agent_id} has been fully closed and resources cleared")
