from fastapi import APIRouter, Depends

from app.application.services.plan_service import PlanService
from app.domain.models.plan import Plan
from app.domain.models.user import User
from app.interfaces.dependencies import get_current_user, get_plan_service
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.plan import (
    GetPlanResponse,
    ListPlansResponse,
    PlanItem,
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
