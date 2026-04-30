"""Aggregated LLM usage / error / latency stats."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.domain.models.user import User
from app.infrastructure.models.sql import LLMCallRow
from app.infrastructure.storage.postgres import get_postgres
from app.interfaces.dependencies import get_current_user
from app.interfaces.schemas.base import APIResponse


router = APIRouter(prefix="/stats", tags=["stats"])


class LLMStatsResponse(BaseModel):
    window_hours: int
    total_calls: int
    error_calls: int
    error_rate: float  # 0..1
    tokens_in: int
    tokens_out: int
    latency_p50_ms: int
    latency_p95_ms: int
    by_model: list[dict]


@router.get("/llm", response_model=APIResponse[LLMStatsResponse])
async def llm_stats(
    window_hours: int = Query(24, ge=1, le=24 * 30),
    session_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
) -> APIResponse[LLMStatsResponse]:
    """Aggregate LLM telemetry over the last `window_hours` hours.

    `session_id` narrows to a single chat. Without it: stats across the user.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    where = [LLMCallRow.created_at >= since, LLMCallRow.user_id == current_user.id]
    if session_id:
        where.append(LLMCallRow.session_id == session_id)

    error_count_expr = func.sum(case((LLMCallRow.error.isnot(None), 1), else_=0))
    p50 = func.percentile_cont(0.5).within_group(LLMCallRow.latency_ms.asc())
    p95 = func.percentile_cont(0.95).within_group(LLMCallRow.latency_ms.asc())

    pg = get_postgres()
    async with pg.session_factory() as db:
        totals = (
            await db.execute(
                select(
                    func.count().label("total"),
                    error_count_expr.label("errors"),
                    func.coalesce(func.sum(LLMCallRow.tokens_in), 0).label("tin"),
                    func.coalesce(func.sum(LLMCallRow.tokens_out), 0).label("tout"),
                    func.coalesce(p50, 0).label("p50"),
                    func.coalesce(p95, 0).label("p95"),
                ).where(*where)
            )
        ).one()

        by_model_rows = (
            await db.execute(
                select(
                    LLMCallRow.model,
                    func.count().label("calls"),
                    error_count_expr.label("errors"),
                    func.coalesce(func.sum(LLMCallRow.tokens_in), 0).label("tin"),
                    func.coalesce(func.sum(LLMCallRow.tokens_out), 0).label("tout"),
                )
                .where(*where)
                .group_by(LLMCallRow.model)
                .order_by(func.count().desc())
            )
        ).all()

    total = int(totals.total or 0)
    errors = int(totals.errors or 0)
    return APIResponse.success(
        LLMStatsResponse(
            window_hours=window_hours,
            total_calls=total,
            error_calls=errors,
            error_rate=(errors / total) if total else 0.0,
            tokens_in=int(totals.tin or 0),
            tokens_out=int(totals.tout or 0),
            latency_p50_ms=int(totals.p50 or 0),
            latency_p95_ms=int(totals.p95 or 0),
            by_model=[
                {
                    "model": r.model,
                    "calls": int(r.calls),
                    "errors": int(r.errors or 0),
                    "tokens_in": int(r.tin),
                    "tokens_out": int(r.tout),
                }
                for r in by_model_rows
            ],
        )
    )
