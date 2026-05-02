from fastapi import APIRouter, Depends, File, UploadFile

from app.application.services.agent_service import AgentService
from app.application.services.file_service import FileService
from app.application.services.project_service import ProjectService
from app.domain.models.user import User
from app.interfaces.dependencies import (
    get_agent_service,
    get_current_user,
    get_file_service,
    get_project_service,
)
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.file import FileInfoResponse
from app.interfaces.schemas.project import (
    CreateProjectRequest,
    CreateProjectResponse,
    ListProjectsResponse,
    ProjectAttachmentsResponse,
    ProjectItem,
    UpdateProjectRequest,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _summary_to_item(p) -> ProjectItem:
    return ProjectItem(
        project_id=p.id,
        name=p.name,
        system_prompt=p.system_prompt,
        session_id=p.session_id,
        title=p.title,
        latest_message=p.latest_message,
        latest_message_at=int(p.latest_message_at.timestamp())
        if p.latest_message_at
        else None,
        status=p.status,
        unread_message_count=p.unread_message_count,
        is_shared=p.is_shared,
    )


@router.get("", response_model=APIResponse[ListProjectsResponse])
async def list_projects(
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[ListProjectsResponse]:
    summaries = await project_service.list_projects(current_user.id)
    # Heal projects that have no session yet (e.g. created before the 1:1
    # invariant existed). One session per project, lazily.
    for summary in summaries:
        if not summary.session_id:
            session = await agent_service.create_session(
                current_user.id,
                project_id=summary.id,
                system_prompt=summary.system_prompt,
            )
            summary.session_id = session.id
            summary.status = session.status
    return APIResponse.success(
        ListProjectsResponse(projects=[_summary_to_item(p) for p in summaries])
    )


@router.post("", response_model=APIResponse[CreateProjectResponse])
async def create_project(
    request: CreateProjectRequest,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[CreateProjectResponse]:
    project = await project_service.create_project(
        current_user.id, request.name, request.system_prompt
    )
    # Project = chat: spin up the session immediately so the sidebar entry
    # has somewhere to navigate to.
    session = await agent_service.create_session(
        current_user.id,
        project_id=project.id,
        system_prompt=project.system_prompt,
    )
    return APIResponse.success(
        CreateProjectResponse(
            project_id=project.id,
            name=project.name,
            system_prompt=project.system_prompt,
            session_id=session.id,
        )
    )


@router.patch("/{project_id}", response_model=APIResponse[None])
async def update_project(
    project_id: str,
    request: UpdateProjectRequest,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> APIResponse[None]:
    if request.name is not None:
        await project_service.rename_project(project_id, current_user.id, request.name)
    if request.system_prompt is not None or "system_prompt" in request.model_fields_set:
        await project_service.update_system_prompt(
            project_id, current_user.id, request.system_prompt
        )
    return APIResponse.success()


@router.delete("/{project_id}", response_model=APIResponse[None])
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[None]:
    # Free sandbox containers + bind-mount dirs BEFORE the bulk DB delete —
    # otherwise running docker containers and host directories outlive the
    # project rows that knew about them.
    await agent_service.cleanup_project_session_resources(
        project_id, current_user.id,
    )
    await project_service.delete_project(project_id, current_user.id)
    return APIResponse.success()


@router.get("/{project_id}/files", response_model=APIResponse[ProjectAttachmentsResponse])
async def list_project_files(
    project_id: str,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> APIResponse[ProjectAttachmentsResponse]:
    project = await project_service.get_project(project_id, current_user.id)
    return APIResponse.success(
        ProjectAttachmentsResponse(
            attachments=[
                {
                    "file_id": a.file_id,
                    "filename": a.filename,
                    "size": a.size,
                    "content_type": a.content_type,
                }
                for a in project.attachments
            ]
        )
    )


@router.post("/{project_id}/files", response_model=APIResponse[FileInfoResponse])
async def add_project_file(
    project_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    file_service: FileService = Depends(get_file_service),
) -> APIResponse[FileInfoResponse]:
    """Upload a file and attach it to a project. The agent will see it in
    `/home/ubuntu/project/<filename>` of every new session."""
    # Make sure the project exists + belongs to the user before touching storage.
    await project_service.get_project(project_id, current_user.id)
    info = await file_service.upload_file(
        file_data=file.file,
        filename=file.filename,
        user_id=current_user.id,
        content_type=file.content_type,
    )
    await project_service.add_attachment(project_id, current_user.id, info)
    return APIResponse.success(await FileInfoResponse.from_file_info(info))


@router.delete("/{project_id}/files/{file_id}", response_model=APIResponse[None])
async def remove_project_file(
    project_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    file_service: FileService = Depends(get_file_service),
) -> APIResponse[None]:
    await project_service.remove_attachment(project_id, current_user.id, file_id)
    # Best-effort: also drop the underlying blob. The user only sees one button
    # so a half-detached attachment would be confusing.
    try:
        await file_service.delete_file(file_id, current_user.id)
    except Exception:
        pass
    return APIResponse.success()
