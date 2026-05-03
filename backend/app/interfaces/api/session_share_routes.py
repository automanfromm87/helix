"""Session sharing endpoints — split out of session_routes.py.

Public-access lookups (`/shared/{id}`) live alongside the
authenticated share/unshare endpoints because they're conceptually one
feature; the FE share dialog hits both paths.
"""
from typing import List

from fastapi import APIRouter, Depends

from app.application.errors.exceptions import NotFoundError
from app.application.services.agent_service import AgentService
from app.domain.models.file import FileInfo
from app.domain.models.user import User
from app.interfaces.dependencies import (
    get_agent_service,
    get_current_user,
    get_file_service,
)
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.event import EventMapper
from app.interfaces.schemas.session import ShareSessionResponse, SharedSessionResponse


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/{session_id}/share", response_model=APIResponse[ShareSessionResponse])
async def share_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[ShareSessionResponse]:
    """Mark the session as shared so unauthenticated GETs to
    `/shared/{session_id}` succeed."""
    await agent_service.share_session(session_id, current_user.id)
    return APIResponse.success(ShareSessionResponse(
        session_id=session_id,
        is_shared=True,
    ))


@router.delete("/{session_id}/share", response_model=APIResponse[ShareSessionResponse])
async def unshare_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[ShareSessionResponse]:
    """Remove public access from a session."""
    await agent_service.unshare_session(session_id, current_user.id)
    return APIResponse.success(ShareSessionResponse(
        session_id=session_id,
        is_shared=False,
    ))


@router.get("/{session_id}/share/files")
async def get_shared_session_files(
    session_id: str,
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[List[FileInfo]]:
    files = await agent_service.get_shared_session_files(session_id)
    for file in files:
        await get_file_service().enrich_with_file_url(file)
    return APIResponse.success(files)


@router.get("/shared/{session_id}", response_model=APIResponse[SharedSessionResponse])
async def get_shared_session(
    session_id: str,
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[SharedSessionResponse]:
    """Public read of a shared session — no auth, but the session must
    have been explicitly shared by its owner."""
    session = await agent_service.get_shared_session(session_id)
    if not session:
        raise NotFoundError("Shared session not found")
    return APIResponse.success(SharedSessionResponse(
        session_id=session.id,
        title=session.title,
        status=session.status,
        events=await EventMapper.events_to_sse_events(session.events),
        is_shared=session.is_shared,
    ))
