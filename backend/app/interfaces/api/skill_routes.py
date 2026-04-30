"""Project-scoped skill CRUD.

Each route validates that the caller owns the project before touching the
underlying skill store. Skills with `project_id IS NULL` (global overrides)
are managed via the admin-only `/api/v1/skills` group.
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.errors.exceptions import NotFoundError
from app.application.services.project_service import ProjectService
from app.domain.models.skill import Skill
from app.domain.models.user import User
from app.domain.repositories.skill_repository import SkillStore
from app.infrastructure.skills.file_skill_repository import FileSkillRepository
from app.interfaces.dependencies import (
    get_admin_user,
    get_current_user,
    get_project_service,
    get_skill_repository,
    get_skill_store,
)
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.skill import (
    ListSkillsResponse,
    SkillItem,
    SkillSource,
    UpsertSkillRequest,
    UpsertSkillResponse,
)

router = APIRouter(tags=["skills"])


def _merge_layers(
    *layers: tuple[SkillSource, Iterable[Skill]],
) -> ListSkillsResponse:
    """Overlay skill layers in argument order — later layers shadow earlier
    ones by name. Returns a sorted response."""
    merged: dict[str, SkillItem] = {}
    for source, skills in layers:
        for skill in skills:
            merged[skill.name] = SkillItem.from_skill(skill, source=source)
    return ListSkillsResponse(
        skills=sorted(merged.values(), key=lambda i: i.name)
    )


async def _ensure_project_owner(
    project_id: str, user: User, project_service: ProjectService
) -> None:
    try:
        await project_service.get_project(project_id, user.id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )


# ---------------------------------------------------------------------------
# Project-scoped CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/skills",
    response_model=APIResponse[ListSkillsResponse],
)
async def list_project_skills(
    project_id: str,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    skill_store: SkillStore = Depends(get_skill_store),
    file_skills: FileSkillRepository = Depends(get_skill_repository),
) -> APIResponse[ListSkillsResponse]:
    """List skills visible to a project — file-based + global DB + project DB.

    Higher layers shadow lower ones by name; the response shows only the
    winning skill plus its source so the FE knows what's editable.
    """
    await _ensure_project_owner(project_id, current_user, project_service)
    global_overrides, project_overrides = await asyncio.gather(
        skill_store.list_for_project(None),
        skill_store.list_for_project(project_id),
    )
    return APIResponse.success(_merge_layers(
        ("file", file_skills.list()),
        ("global", global_overrides),
        ("project", project_overrides),
    ))


@router.put(
    "/projects/{project_id}/skills/{name}",
    response_model=APIResponse[UpsertSkillResponse],
)
async def upsert_project_skill(
    project_id: str,
    name: str,
    request: UpsertSkillRequest,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    skill_store: SkillStore = Depends(get_skill_store),
) -> APIResponse[UpsertSkillResponse]:
    """Create or update a project-scoped skill."""
    await _ensure_project_owner(project_id, current_user, project_service)
    skill = await skill_store.upsert(
        project_id=project_id,
        name=name,
        description=request.description,
        body=request.body,
    )
    return APIResponse.success(UpsertSkillResponse(
        skill=SkillItem.from_skill(skill, source="project"),
    ))


@router.delete(
    "/projects/{project_id}/skills/{name}",
    response_model=APIResponse[None],
)
async def delete_project_skill(
    project_id: str,
    name: str,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    skill_store: SkillStore = Depends(get_skill_store),
) -> APIResponse[None]:
    await _ensure_project_owner(project_id, current_user, project_service)
    deleted = await skill_store.delete(project_id=project_id, name=name)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found"
        )
    return APIResponse.success()


# ---------------------------------------------------------------------------
# Admin-only global overrides
# ---------------------------------------------------------------------------


@router.get("/skills", response_model=APIResponse[ListSkillsResponse])
async def list_all_skills(
    _user: User = Depends(get_current_user),
    skill_store: SkillStore = Depends(get_skill_store),
    file_skills: FileSkillRepository = Depends(get_skill_repository),
) -> APIResponse[ListSkillsResponse]:
    """Read-only list of file-based skills + global DB overrides.

    Available to any authenticated user — the body of a skill is what the
    agent sees on `load_skill`, and the description is the trigger
    documentation, neither of which is sensitive. Mutation routes
    (PUT/DELETE) remain admin-only.
    """
    global_overrides = await skill_store.list_for_project(None)
    return APIResponse.success(_merge_layers(
        ("file", file_skills.list()),
        ("global", global_overrides),
    ))


@router.put("/skills/{name}", response_model=APIResponse[UpsertSkillResponse])
async def upsert_global_skill(
    name: str,
    request: UpsertSkillRequest,
    _admin: User = Depends(get_admin_user),
    skill_store: SkillStore = Depends(get_skill_store),
) -> APIResponse[UpsertSkillResponse]:
    skill = await skill_store.upsert(
        project_id=None,
        name=name,
        description=request.description,
        body=request.body,
    )
    return APIResponse.success(UpsertSkillResponse(
        skill=SkillItem.from_skill(skill, source="global"),
    ))


@router.delete("/skills/{name}", response_model=APIResponse[None])
async def delete_global_skill(
    name: str,
    _admin: User = Depends(get_admin_user),
    skill_store: SkillStore = Depends(get_skill_store),
) -> APIResponse[None]:
    deleted = await skill_store.delete(project_id=None, name=name)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found"
        )
    return APIResponse.success()
