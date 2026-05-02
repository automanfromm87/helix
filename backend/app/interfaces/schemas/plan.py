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
    commit_sha: Optional[str] = None


class ListPlansResponse(BaseModel):
    plans: List[PlanItem]


class GetPlanResponse(BaseModel):
    plan: Optional[PlanItem] = None


class PlanDiffResponse(BaseModel):
    plan_id: str
    commit_sha: Optional[str] = None
    diff: str = ""


class PlanRestoreResponse(BaseModel):
    plan_id: str
    restored: bool


class PlanForkResponse(BaseModel):
    plan_id: str
    new_session_id: str


class PlanForkManyRequest(BaseModel):
    """N parallel forks from the same plan, used for compare-variants.
    `count` is how many forks to spawn; `labels` lets the FE preset a
    column label for each (e.g. "minimalist" / "bold" / "experimental").
    Server caps `count` to prevent DOS-via-fork."""

    count: int = 3
    labels: Optional[List[str]] = None


class PlanForkManySession(BaseModel):
    session_id: str
    project_id: str
    label: Optional[str] = None


class PlanForkManyResponse(BaseModel):
    plan_id: str
    sessions: List[PlanForkManySession]
