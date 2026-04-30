from typing import List, Optional

from pydantic import BaseModel

from app.domain.models.plan import PlanStatus, TaskStatus


class TaskItem(BaseModel):
    task_id: str
    plan_id: str
    position: int
    title: str
    details: Optional[str] = None
    status: TaskStatus
    result: Optional[str] = None
    error: Optional[str] = None
    retries: int = 0


class PlanItem(BaseModel):
    plan_id: str
    session_id: str
    title: str
    goal: str
    status: PlanStatus
    error: Optional[str] = None
    tasks: List[TaskItem]


class ListPlansResponse(BaseModel):
    plans: List[PlanItem]


class GetPlanResponse(BaseModel):
    plan: Optional[PlanItem] = None
