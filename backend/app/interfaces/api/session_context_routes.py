"""Per-session context-file management endpoints — split out of
session_routes.py.

Context files are Markdown reference docs the user attaches via the
session settings dialog. Distinct from chat attachments (which travel
with a single message) and from project Skills (global registry); they
get rendered into the agent's system prompt every turn unless retrieval-
only mode is on.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.application.errors.exceptions import NotFoundError
from app.application.services.agent_service import AgentService
from app.domain.models.user import User
from app.interfaces.dependencies import get_agent_service, get_current_user
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.session import (
    ContextFileFromUrlRequest,
    ContextFileListResponse,
    ContextFileSummary,
    ContextFileUploadRequest,
    RetrievalModeRequest,
    SessionSettingsResponse,
)


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get(
    "/{session_id}/context-files",
    response_model=APIResponse[ContextFileListResponse],
)
async def list_context_files(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[ContextFileListResponse]:
    """List Markdown reference docs attached to this session. Contents
    themselves are NOT in the response — only filename, size, created_at
    — to keep the list view light. The agent reads contents server-side
    at task-creation time."""
    files = await agent_service.list_context_files(session_id, current_user.id)
    return APIResponse.success(
        ContextFileListResponse(
            files=[
                ContextFileSummary(
                    id=f.id,
                    filename=f.filename,
                    size=f.size,
                    created_at=f.created_at,
                )
                for f in files
            ]
        )
    )


@router.post(
    "/{session_id}/context-files",
    response_model=APIResponse[ContextFileSummary],
)
async def add_context_file(
    session_id: str,
    body: ContextFileUploadRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[ContextFileSummary]:
    """Attach a Markdown reference document. Body is JSON `{filename,
    content}`; service-layer enforces size + count caps."""
    try:
        cf = await agent_service.add_context_file(
            session_id, current_user.id, body.filename, body.content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse.success(
        ContextFileSummary(
            id=cf.id,
            filename=cf.filename,
            size=cf.size,
            created_at=cf.created_at,
        )
    )


@router.delete(
    "/{session_id}/context-files/{file_id}",
    response_model=APIResponse[None],
)
async def delete_context_file(
    session_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[None]:
    await agent_service.remove_context_file(session_id, current_user.id, file_id)
    return APIResponse.success(None)


@router.post(
    "/{session_id}/context-files/from-url",
    response_model=APIResponse[ContextFileSummary],
)
async def add_context_file_from_url(
    session_id: str,
    body: ContextFileFromUrlRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[ContextFileSummary]:
    """Fetch a URL, convert HTML → Markdown, attach as a context file."""
    try:
        cf = await agent_service.add_context_file_from_url(
            session_id, current_user.id, body.url,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse.success(
        ContextFileSummary(
            id=cf.id,
            filename=cf.filename,
            size=cf.size,
            created_at=cf.created_at,
        )
    )


@router.get(
    "/{session_id}/settings",
    response_model=APIResponse[SessionSettingsResponse],
)
async def get_session_settings(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[SessionSettingsResponse]:
    session = await agent_service.get_session(session_id, current_user.id)
    if not session:
        raise NotFoundError("Session not found")
    return APIResponse.success(
        SessionSettingsResponse(
            retrieval_only_context=session.retrieval_only_context,
        )
    )


@router.post(
    "/{session_id}/retrieval-mode",
    response_model=APIResponse[None],
)
async def set_retrieval_mode(
    session_id: str,
    body: RetrievalModeRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[None]:
    """Toggle retrieval-only mode for context files. When enabled, the
    agent only sees attached files via the `retrieve` tool."""
    await agent_service.set_retrieval_only(session_id, current_user.id, body.enabled)
    return APIResponse.success(None)
