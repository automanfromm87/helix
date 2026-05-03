from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sse_starlette.sse import EventSourceResponse
from typing import AsyncGenerator, List, Optional
from sse_starlette.event import ServerSentEvent
from datetime import datetime
import asyncio
import json
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
    ChatRequest, ContextFileFromUrlRequest, ContextFileListResponse,
    ContextFileSummary, ContextFileUploadRequest, CreateSessionRequest,
    CreateSessionResponse, GetSessionResponse, ListSessionItem,
    ListSessionResponse, RegenerateRequest, RetrievalModeRequest,
    SessionSettingsResponse, ShareSessionResponse, SharedSessionResponse,
    ShellViewRequest, ShellViewResponse, UpdateSessionProjectRequest,
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

@router.post("/{session_a_id}/merge-with/{session_b_id}")
async def merge_two_sessions(
    session_a_id: str,
    session_b_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
):
    """Merge one session's branch into another. Direction is inferred
    from the branches (the one on `fork/*` is the source). On clean
    merge or LLM-resolved merge, a new tagged plan version lands in
    the target session."""
    try:
        result = await agent_service.merge_two_sessions(
            session_a_id, session_b_id, current_user.id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse.success(result)


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

@router.post("/{session_id}/chat")
async def chat(
    session_id: str,
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service)
) -> EventSourceResponse:
    async def event_generator() -> AsyncGenerator[ServerSentEvent, None]:
        with bind_log_context(session_id=session_id, user_id=current_user.id):
            try:
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
            except asyncio.CancelledError:
                # Client disconnected — let the cancellation propagate so
                # the underlying chat() generator runs its finally blocks.
                raise
            except Exception as e:
                # Surface fatal errors as a final SSE event so the FE shows
                # the user a real message instead of a transport-level
                # "stream closed unexpectedly" toast. Then close cleanly.
                logger.exception("chat SSE generator crashed")
                error_payload = {
                    "event_id": "0",
                    "timestamp": int(datetime.now().timestamp()),
                    "error": f"{type(e).__name__}: {e}" or "Internal error",
                }
                yield ServerSentEvent(
                    event="error",
                    data=json.dumps(error_payload),
                )
                yield ServerSentEvent(
                    event="done",
                    data=json.dumps({
                        "event_id": "0",
                        "timestamp": int(datetime.now().timestamp()),
                    }),
                )

    return EventSourceResponse(event_generator())

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

