from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from sse_starlette.sse import EventSourceResponse
from typing import AsyncGenerator, List, Optional
from sse_starlette.event import ServerSentEvent
from datetime import datetime
import asyncio
import websockets
import logging
from app.interfaces.dependencies import get_file_service

from app.application.services.agent_service import AgentService
from app.application.services.token_service import TokenService
from app.application.errors.exceptions import NotFoundError, UnauthorizedError
from app.infrastructure.logging import bind_log_context
from app.interfaces.dependencies import get_agent_service, get_current_user, get_optional_current_user, get_token_service, verify_signature_websocket
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.session import (
    ChatRequest, ShellViewRequest, CreateSessionRequest, CreateSessionResponse,
    GetSessionResponse, ListSessionItem, ListSessionResponse, RegenerateRequest,
    ShellViewResponse, ShareSessionResponse, SharedSessionResponse,
    UpdateSessionProjectRequest,
)
from app.application.services.project_service import ProjectService
from app.interfaces.dependencies import get_project_service
from app.interfaces.schemas.file import (
    FileViewRequest, FileViewResponse,
    FileListRequest, FileListResponse,
)
from app.interfaces.schemas.resource import AccessTokenRequest, SignedUrlResponse
from app.interfaces.schemas.event import EventMapper
from app.domain.models.file import FileInfo
from app.domain.models.user import User

logger = logging.getLogger(__name__)
SESSION_POLL_INTERVAL = 5

router = APIRouter(prefix="/sessions", tags=["sessions"])

@router.get("/search", response_model=APIResponse[ListSessionResponse])
async def search_sessions(
    q: str = Query("", description="Free-text query"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[ListSessionResponse]:
    summaries = await agent_service.search_sessions(current_user.id, q, limit)
    items = [
        ListSessionItem(
            session_id=s.id,
            project_id=s.project_id,
            title=s.title,
            status=s.status,
            unread_message_count=s.unread_message_count,
            latest_message=s.latest_message,
            latest_message_at=int(s.latest_message_at.timestamp()) if s.latest_message_at else None,
            is_shared=s.is_shared,
        )
        for s in summaries
    ]
    return APIResponse.success(ListSessionResponse(sessions=items))


@router.put("", response_model=APIResponse[CreateSessionResponse])
async def create_session(
    request: CreateSessionRequest = CreateSessionRequest(),
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
    project_service: ProjectService = Depends(get_project_service),
) -> APIResponse[CreateSessionResponse]:
    project_id = request.project_id or await project_service.get_default_project_id(current_user.id)
    # Snapshot project context (system prompt + accumulated cross-session
    # memory) into the session so future edits to the project don't shift this
    # in-flight chat's behavior.
    project = await project_service.get_project(project_id, current_user.id)
    snapshot_parts = []
    if project.system_prompt:
        snapshot_parts.append(project.system_prompt.strip())
    if project.shared_memory:
        snapshot_parts.append(
            "## Earlier sessions in this project\n" + project.shared_memory.strip()
        )
    system_prompt = "\n\n".join(snapshot_parts) if snapshot_parts else None
    session = await agent_service.create_session(
        current_user.id, project_id=project_id, system_prompt=system_prompt
    )
    return APIResponse.success(
        CreateSessionResponse(
            session_id=session.id,
            project_id=session.project_id,
        )
    )

@router.get("/{session_id}", response_model=APIResponse[GetSessionResponse])
async def get_session(
    session_id: str,
    events_limit: Optional[int] = Query(
        None,
        ge=1,
        le=2000,
        description=(
            "Cap on number of events returned (latest first). Used by the "
            "chat page to keep the initial payload small on long sessions."
        ),
    ),
    events_before: Optional[str] = Query(
        None,
        description=(
            "Event id cursor — return events strictly older than this id. "
            "Pair with `events_limit` for paginated history loading."
        ),
    ),
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[GetSessionResponse]:
    session = await agent_service.get_session(
        session_id,
        current_user.id,
        events_limit=events_limit,
        events_before=events_before,
    )
    if not session:
        raise NotFoundError("Session not found")
    return APIResponse.success(GetSessionResponse(
        session_id=session.id,
        project_id=session.project_id,
        title=session.title,
        status=session.status,
        events=await EventMapper.events_to_sse_events(session.events),
        is_shared=session.is_shared
    ))

@router.patch("/{session_id}/project", response_model=APIResponse[None])
async def move_session_to_project(
    session_id: str,
    request: UpdateSessionProjectRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[None]:
    await agent_service.move_session_to_project(session_id, current_user.id, request.project_id)
    return APIResponse.success()

@router.delete("/{session_id}", response_model=APIResponse[None])
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[None]:
    await agent_service.delete_session(session_id, current_user.id)
    return APIResponse.success()

@router.post("/{session_id}/stop", response_model=APIResponse[None])
async def stop_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[None]:
    await agent_service.stop_session(session_id, current_user.id)
    return APIResponse.success()

@router.post("/{session_id}/regenerate", response_model=APIResponse[None])
async def regenerate_from_message(
    session_id: str,
    request: RegenerateRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[None]:
    """Lop off events from `from_event_id` onward, then the SSE chat client
    submits the new message via the regular /chat endpoint."""
    await agent_service.regenerate_from_message(
        session_id=session_id,
        user_id=current_user.id,
        from_event_id=request.from_event_id,
        message=request.message,
        attachments=request.attachments,
    )
    return APIResponse.success()


@router.post("/{session_id}/clear_unread_message_count", response_model=APIResponse[None])
async def clear_unread_message_count(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[None]:
    await agent_service.clear_unread_message_count(session_id, current_user.id)
    return APIResponse.success()

@router.get("", response_model=APIResponse[ListSessionResponse])
async def get_all_sessions(
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[ListSessionResponse]:
    summaries = await agent_service.get_all_sessions(current_user.id)
    session_items = [
        ListSessionItem(
            session_id=s.id,
            project_id=s.project_id,
            title=s.title,
            status=s.status,
            unread_message_count=s.unread_message_count,
            latest_message=s.latest_message,
            latest_message_at=int(s.latest_message_at.timestamp()) if s.latest_message_at else None,
            is_shared=s.is_shared
        ) for s in summaries
    ]
    return APIResponse.success(ListSessionResponse(sessions=session_items))

@router.post("")
async def stream_sessions(
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> EventSourceResponse:
    async def event_generator() -> AsyncGenerator[ServerSentEvent, None]:
        while True:
            summaries = await agent_service.get_all_sessions(current_user.id)
            session_items = [
                ListSessionItem(
                    session_id=s.id,
                    title=s.title,
                    status=s.status,
                    unread_message_count=s.unread_message_count,
                    latest_message=s.latest_message,
                    latest_message_at=int(s.latest_message_at.timestamp()) if s.latest_message_at else None,
                    is_shared=s.is_shared
                ) for s in summaries
            ]
            yield ServerSentEvent(
                event="sessions",
                data=ListSessionResponse(sessions=session_items).model_dump_json()
            )
            await asyncio.sleep(SESSION_POLL_INTERVAL)
    return EventSourceResponse(event_generator())

@router.post("/{session_id}/chat")
async def chat(
    session_id: str,
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> EventSourceResponse:
    async def event_generator() -> AsyncGenerator[ServerSentEvent, None]:
        with bind_log_context(session_id=session_id, user_id=current_user.id):
            async for event in agent_service.chat(
                session_id=session_id,
                user_id=current_user.id,
                message=request.message,
                timestamp=datetime.fromtimestamp(request.timestamp) if request.timestamp else None,
                event_id=request.event_id,
                attachments=request.attachments
            ):
                logger.debug(f"Received event from chat: {event}")
                sse_event = await EventMapper.event_to_sse_event(event)
                if sse_event:
                    yield ServerSentEvent(
                        event=sse_event.event,
                        data=sse_event.data.model_dump_json() if sse_event.data else None
                    )

    return EventSourceResponse(event_generator())

@router.post("/{session_id}/shell")
async def view_shell(
    session_id: str,
    request: ShellViewRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[ShellViewResponse]:
    """View shell session output
    
    If the agent does not exist or fails to get shell output, an appropriate exception will be thrown and handled by the global exception handler
    
    Args:
        session_id: Session ID
        request: Shell view request containing session ID
        
    Returns:
        APIResponse with shell output
    """
    result = await agent_service.shell_view(session_id, request.session_id, current_user.id)
    return APIResponse.success(result)

@router.post("/{session_id}/file")
async def view_file(
    session_id: str,
    request: FileViewRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[FileViewResponse]:
    """View file content
    
    If the agent does not exist or fails to get file content, an appropriate exception will be thrown and handled by the global exception handler
    
    Args:
        session_id: Session ID
        request: File view request containing file path
        
    Returns:
        APIResponse with file content
    """
    result = await agent_service.file_view(session_id, request.file, current_user.id)
    return APIResponse.success(result)


@router.post("/{session_id}/file/list", response_model=APIResponse[FileListResponse])
async def list_dir(
    session_id: str,
    request: FileListRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[FileListResponse]:
    """List one directory level inside the session's sandbox.

    Used by the FE explorer tree — returns dirs sorted first then
    alphabetical, with `.git` / `node_modules` etc. filtered by default.
    """
    data = await agent_service.file_list(
        session_id=session_id,
        dir_path=request.path,
        user_id=current_user.id,
        show_hidden=bool(request.show_hidden),
    )
    return APIResponse.success(FileListResponse(**data))


@router.websocket("/{session_id}/vnc")
async def vnc_websocket(
    websocket: WebSocket,
    session_id: str,
    signature: str = Depends(verify_signature_websocket),
    agent_service: AgentService = Depends(get_agent_service)
) -> None:
    """VNC WebSocket endpoint (binary mode)
    
    Establishes a connection with the VNC WebSocket service in the sandbox environment and forwards data bidirectionally
    Supports authentication via signed URL with signature verification
    
    Args:
        websocket: WebSocket connection
        session_id: Session ID
        signature: Verified signature from dependency injection
    """
    
    await websocket.accept(subprotocol="binary")
    logger.info(f"Accepted WebSocket connection for session {session_id}")
    
    try:
        # Get sandbox environment address with user validation
        sandbox_ws_url = await agent_service.get_vnc_url(session_id)

        logger.info(f"Connecting to VNC WebSocket at {sandbox_ws_url}")
    
        # Connect to sandbox WebSocket
        async with websockets.connect(sandbox_ws_url) as sandbox_ws:
            logger.info(f"Connected to VNC WebSocket at {sandbox_ws_url}")
            # Create two tasks to forward data bidirectionally
            async def forward_to_sandbox():
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await sandbox_ws.send(data)
                except WebSocketDisconnect:
                    logger.info("Web -> VNC connection closed")
                    pass
                except Exception as e:
                    logger.error(f"Error forwarding data to sandbox: {e}")
            
            async def forward_from_sandbox():
                try:
                    while True:
                        data = await sandbox_ws.recv()
                        await websocket.send_bytes(data)
                except websockets.exceptions.ConnectionClosed:
                    logger.info("VNC -> Web connection closed")
                    pass
                except Exception as e:
                    logger.error(f"Error forwarding data from sandbox: {e}")
            
            # Run two forwarding tasks concurrently
            forward_task1 = asyncio.create_task(forward_to_sandbox())
            forward_task2 = asyncio.create_task(forward_from_sandbox())
            
            # Wait for either task to complete (meaning connection has closed)
            done, pending = await asyncio.wait(
                [forward_task1, forward_task2],
                return_when=asyncio.FIRST_COMPLETED
            )

            logger.info("WebSocket connection closed")
            
            # Cancel pending tasks
            for task in pending:
                task.cancel()
    
    except ConnectionError as e:
        logger.error(f"Unable to connect to sandbox environment: {str(e)}")
        await websocket.close(code=1011, reason=f"Unable to connect to sandbox environment: {str(e)}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        await websocket.close(code=1011, reason=f"WebSocket error: {str(e)}")

@router.get("/{session_id}/files")
async def get_session_files(
    session_id: str,
    current_user: Optional[User] = Depends(get_optional_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[List[FileInfo]]:
    if not current_user and not await agent_service.is_session_shared(session_id):
        raise UnauthorizedError()
    files = await agent_service.get_session_files(session_id, current_user.id if current_user else None)
    return APIResponse.success(files)


@router.websocket("/{session_id}/shell/stream")
async def shell_stream_websocket(
    websocket: WebSocket,
    session_id: str,
    cols: int = 80,
    rows: int = 24,
    cwd: Optional[str] = None,
    signature: str = Depends(verify_signature_websocket),
    agent_service: AgentService = Depends(get_agent_service),
) -> None:
    """Interactive pty shell over WebSocket.

    Authenticated by signed URL (same scheme as /vnc) — the FE first
    POSTs to /shell/stream/signed-url, gets back a tokenised WS URL,
    then opens the WS. We then proxy bidirectionally to the sandbox's
    own /shell/stream WS endpoint.

    Wire protocol:
      client → server  binary    raw stdin (xterm.js keystrokes)
      client → server  text      JSON control: {"type":"resize","cols":N,"rows":M}
      server → client  binary    raw pty stdout/stderr
    """
    await websocket.accept()
    logger.info(f"Accepted shell stream WS for session {session_id}")

    try:
        sandbox_ws_url = await agent_service.get_shell_stream_url(
            session_id, cols=cols, rows=rows, cwd=cwd,
        )
    except NotFoundError as exc:
        await websocket.close(code=1008, reason=str(exc))
        return
    except Exception as exc:
        logger.error(f"shell-stream URL failed for {session_id}: {exc}")
        await websocket.close(code=1011, reason="sandbox unavailable")
        return

    try:
        async with websockets.connect(sandbox_ws_url) as sandbox_ws:
            logger.info(f"Connected to sandbox shell stream {sandbox_ws_url}")

            async def upstream() -> None:
                # FE → sandbox: forward both binary (stdin) and text
                # (JSON control) frames untouched.
                try:
                    while True:
                        msg = await websocket.receive()
                        mtype = msg.get("type")
                        if mtype == "websocket.disconnect":
                            return
                        if "bytes" in msg and msg["bytes"] is not None:
                            await sandbox_ws.send(msg["bytes"])
                        elif "text" in msg and msg["text"] is not None:
                            await sandbox_ws.send(msg["text"])
                except WebSocketDisconnect:
                    return
                except Exception as e:
                    logger.warning(f"shell upstream forward error: {e}")

            async def downstream() -> None:
                # Sandbox → FE: pty stdout always arrives as binary.
                try:
                    async for data in sandbox_ws:
                        if isinstance(data, (bytes, bytearray)):
                            await websocket.send_bytes(data)
                        else:
                            await websocket.send_text(data)
                except websockets.exceptions.ConnectionClosed:
                    return
                except Exception as e:
                    logger.warning(f"shell downstream forward error: {e}")

            t_up = asyncio.create_task(upstream(), name="shell.upstream")
            t_dn = asyncio.create_task(downstream(), name="shell.downstream")
            done, pending = await asyncio.wait(
                {t_up, t_dn}, return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except ConnectionError as exc:
        logger.error(f"shell-stream sandbox connect failed: {exc}")
        try:
            await websocket.close(code=1011, reason="sandbox connection failed")
        except Exception:
            pass
    except Exception as exc:
        logger.error(f"shell-stream proxy crashed: {exc}")
        try:
            await websocket.close(code=1011, reason="proxy error")
        except Exception:
            pass


@router.post("/{session_id}/shell/stream/signed-url", response_model=APIResponse[SignedUrlResponse])
async def create_shell_stream_signed_url(
    session_id: str,
    request_data: AccessTokenRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
    token_service: TokenService = Depends(get_token_service),
) -> APIResponse[SignedUrlResponse]:
    """Mint a short-lived signed URL the FE can open the shell stream WS
    against without normal auth headers (browsers can't set Authorization
    on a WebSocket handshake)."""
    expire_minutes = min(request_data.expire_minutes, 15)
    session = await agent_service.get_session(session_id, current_user.id)
    if not session:
        raise NotFoundError("Session not found")
    ws_base_url = f"/api/v1/sessions/{session_id}/shell/stream"
    signed_url = token_service.create_signed_url(
        base_url=ws_base_url,
        expire_minutes=expire_minutes,
    )
    logger.info(
        f"Created signed shell-stream URL for user {current_user.id}, session {session_id}",
    )
    return APIResponse.success(SignedUrlResponse(
        signed_url=signed_url,
        expires_in=expire_minutes * 60,
    ))


@router.post("/{session_id}/vnc/signed-url", response_model=APIResponse[SignedUrlResponse])
async def create_vnc_signed_url(
    session_id: str,
    request_data: AccessTokenRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
    token_service: TokenService = Depends(get_token_service)
) -> APIResponse[SignedUrlResponse]:
    """Generate signed URL for VNC WebSocket access
    
    This endpoint creates a signed URL that allows temporary access to the VNC
    WebSocket for a specific session without requiring authentication headers.
    """
    
    # Validate expiration time (max 15 minutes)
    expire_minutes = request_data.expire_minutes
    if expire_minutes > 15:
        expire_minutes = 15
    
    # Check if session exists and belongs to user
    session = await agent_service.get_session(session_id, current_user.id)
    if not session:
        raise NotFoundError("Session not found")
    
    # Create signed URL for VNC WebSocket
    ws_base_url = f"/api/v1/sessions/{session_id}/vnc"
    signed_url = token_service.create_signed_url(
        base_url=ws_base_url,
        expire_minutes=expire_minutes
    )
    
    logger.info(f"Created signed URL for VNC access for user {current_user.id}, session {session_id}")
    
    return APIResponse.success(SignedUrlResponse(
        signed_url=signed_url,
        expires_in=expire_minutes * 60,
    ))


@router.post("/{session_id}/share", response_model=APIResponse[ShareSessionResponse])
async def share_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[ShareSessionResponse]:
    """Share a session to make it publicly accessible
    
    This endpoint marks a session as shared, allowing it to be accessed
    without authentication using the shared session endpoint.
    """
    await agent_service.share_session(session_id, current_user.id)
    return APIResponse.success(ShareSessionResponse(
        session_id=session_id,
        is_shared=True
    ))

@router.get("/{session_id}/share/files")
async def get_shared_session_files(
    session_id: str,
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[List[FileInfo]]:
    files = await agent_service.get_shared_session_files(session_id)
    for file in files:
        await get_file_service().enrich_with_file_url(file)
    return APIResponse.success(files)


@router.delete("/{session_id}/share", response_model=APIResponse[ShareSessionResponse])
async def unshare_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[ShareSessionResponse]:
    """Unshare a session to make it private again
    
    This endpoint marks a session as not shared, removing public access.
    """
    await agent_service.unshare_session(session_id, current_user.id)
    return APIResponse.success(ShareSessionResponse(
        session_id=session_id,
        is_shared=False
    ))


@router.get("/shared/{session_id}", response_model=APIResponse[SharedSessionResponse])
async def get_shared_session(
    session_id: str,
    agent_service: AgentService = Depends(get_agent_service)
) -> APIResponse[SharedSessionResponse]:
    """Get a shared session without authentication
    
    This endpoint allows public access to sessions that have been marked as shared.
    No authentication is required, but the session must be explicitly shared.
    """
    session = await agent_service.get_shared_session(session_id)
    if not session:
        raise NotFoundError("Shared session not found")
    
    return APIResponse.success(SharedSessionResponse(
        session_id=session.id,
        title=session.title,
        status=session.status,
        events=await EventMapper.events_to_sse_events(session.events),
        is_shared=session.is_shared
    ))