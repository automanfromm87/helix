from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.application.services.agent_service import AgentService
from app.application.services.plan_service import PlanService
from app.application.services.project_service import ProjectService
from app.core.config import get_settings
from app.domain.models.plan import Plan
from app.domain.models.user import User
from app.infrastructure.external.git.plan_versioning import (
    diff_plan,
    restore_to_plan,
)
from app.interfaces.dependencies import (
    get_agent_service,
    get_current_user,
    get_plan_service,
    get_project_service,
)
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.plan import (
    GetPlanResponse,
    ListPlansResponse,
    PlanDiffResponse,
    PlanForkManyRequest,
    PlanForkManyResponse,
    PlanForkManySession,
    PlanForkResponse,
    PlanItem,
    PlanRestoreResponse,
    TaskItem,
)


router = APIRouter(tags=["plans"])


def _to_item(plan: Plan) -> PlanItem:
    return PlanItem(
        plan_id=plan.id,
        session_id=plan.session_id,
        title=plan.title,
        goal=plan.goal,
        status=plan.status,
        error=plan.error,
        commit_sha=plan.commit_sha,
        tasks=[
            TaskItem(
                task_id=t.id,
                plan_id=t.plan_id,
                position=t.position,
                title=t.title,
                details=t.details,
                status=t.status,
                result=t.result,
                error=t.error,
                retries=t.retries,
            )
            for t in sorted(plan.tasks, key=lambda t: t.position)
        ],
    )


def _project_path_for(session_id: str) -> Path:
    return Path(get_settings().sandbox_data_host_root) / session_id / "project"


@router.get(
    "/sessions/{session_id}/plans",
    response_model=APIResponse[ListPlansResponse],
)
async def list_session_plans(
    session_id: str,
    current_user: User = Depends(get_current_user),
    plan_service: PlanService = Depends(get_plan_service),
) -> APIResponse[ListPlansResponse]:
    plans = await plan_service.list_plans(session_id, current_user.id)
    return APIResponse.success(
        ListPlansResponse(plans=[_to_item(p) for p in plans])
    )


@router.get(
    "/sessions/{session_id}/plans/current",
    response_model=APIResponse[GetPlanResponse],
)
async def get_current_session_plan(
    session_id: str,
    current_user: User = Depends(get_current_user),
    plan_service: PlanService = Depends(get_plan_service),
) -> APIResponse[GetPlanResponse]:
    plan = await plan_service.get_current_plan(session_id, current_user.id)
    return APIResponse.success(
        GetPlanResponse(plan=_to_item(plan) if plan else None)
    )


@router.get(
    "/plans/{plan_id}",
    response_model=APIResponse[GetPlanResponse],
)
async def get_plan(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    plan_service: PlanService = Depends(get_plan_service),
) -> APIResponse[GetPlanResponse]:
    plan = await plan_service.get_plan(plan_id, current_user.id)
    return APIResponse.success(GetPlanResponse(plan=_to_item(plan)))


@router.get(
    "/plans/{plan_id}/diff",
    response_model=APIResponse[PlanDiffResponse],
)
async def get_plan_diff(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    plan_service: PlanService = Depends(get_plan_service),
) -> APIResponse[PlanDiffResponse]:
    """Unified diff between this plan's snapshot and its predecessor.
    Returns an empty diff string if the plan never produced a commit
    (e.g. plans that completed without any file changes)."""
    plan = await plan_service.get_plan(plan_id, current_user.id)
    diff = await diff_plan(_project_path_for(plan.session_id), plan_id)
    return APIResponse.success(
        PlanDiffResponse(plan_id=plan_id, commit_sha=plan.commit_sha, diff=diff)
    )


@router.post(
    "/plans/{plan_id}/restore",
    response_model=APIResponse[PlanRestoreResponse],
)
async def restore_plan(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    plan_service: PlanService = Depends(get_plan_service),
) -> APIResponse[PlanRestoreResponse]:
    """Hard-reset the project tree to this plan's snapshot.
    Destructive — caller is responsible for confirming with the user."""
    plan = await plan_service.get_plan(plan_id, current_user.id)
    if not plan.commit_sha:
        raise HTTPException(status_code=400, detail="Plan has no commit to restore")
    ok = await restore_to_plan(_project_path_for(plan.session_id), plan_id)
    return APIResponse.success(PlanRestoreResponse(plan_id=plan_id, restored=ok))


@router.post(
    "/plans/{plan_id}/fork",
    response_model=APIResponse[PlanForkResponse],
)
async def fork_plan(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
    plan_service: PlanService = Depends(get_plan_service),
    project_service: ProjectService = Depends(get_project_service),
) -> APIResponse[PlanForkResponse]:
    """Create a new session that starts from this plan's snapshot on a
    fresh git branch. The fork goes into a brand-new project so the
    sidebar (1 project = 1 visible session) shows original + fork as
    siblings instead of one displacing the other.
    Returns the new session id; FE navigates there."""
    try:
        plan = await plan_service.get_plan(plan_id, current_user.id)
        fork_project_obj = await project_service.create_project(
            current_user.id,
            name=f"Fork: {plan.title or plan.goal or 'plan'}"[:120],
        )
        new_session = await agent_service.fork_from_plan(
            plan_id, current_user.id, target_project_id=fork_project_obj.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse.success(
        PlanForkResponse(plan_id=plan_id, new_session_id=new_session.id)
    )


@router.post(
    "/plans/{plan_id}/fork-many",
    response_model=APIResponse[PlanForkManyResponse],
)
async def fork_plan_many(
    plan_id: str,
    body: PlanForkManyRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
    plan_service: PlanService = Depends(get_plan_service),
    project_service: ProjectService = Depends(get_project_service),
) -> APIResponse[PlanForkManyResponse]:
    """Spawn N parallel forks from one plan for side-by-side compare.

    Each fork is structurally identical to a single `/fork` call —
    fresh project, fresh session, sandbox spinning up in the background
    via the registry. The FE collects the returned session ids and
    navigates to a compare view that shows their previews
    side-by-side.

    Hard cap of 6 because beyond that the compare page can't show
    iframes large enough to be useful, and we'd rather slow the user
    down than let them DOS the local docker daemon. Forks are
    sequential at the route layer (one git copytree at a time) — the
    bg-sandbox-spawn happens via asyncio.create_task so the API
    returns once project state is staged for all variants.
    """
    if body.count < 2:
        raise HTTPException(
            status_code=400, detail="count must be at least 2",
        )
    if body.count > 6:
        raise HTTPException(status_code=400, detail="count must be at most 6")
    if body.labels is not None and len(body.labels) != body.count:
        raise HTTPException(
            status_code=400,
            detail="labels length must match count",
        )

    try:
        plan = await plan_service.get_plan(plan_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sessions: list[PlanForkManySession] = []
    for i in range(body.count):
        label = body.labels[i] if body.labels else None
        # Project name embeds the variant index so the sidebar reflects
        # the relationship at a glance — `Variant 1: Fork: <plan>`.
        base = plan.title or plan.goal or "plan"
        suffix = f": {label}" if label else f" #{i + 1}"
        proj = await project_service.create_project(
            current_user.id,
            name=f"Variant{suffix} ({base})"[:120],
        )
        try:
            new_session = await agent_service.fork_from_plan(
                plan_id, current_user.id, target_project_id=proj.id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        sessions.append(
            PlanForkManySession(
                session_id=new_session.id,
                project_id=proj.id,
                label=label,
            )
        )

    return APIResponse.success(
        PlanForkManyResponse(plan_id=plan_id, sessions=sessions)
    )
