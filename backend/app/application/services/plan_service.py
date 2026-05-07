"""Re-export shim. PlanService now lives in `app.domain.services.plan_service`
because it's pure domain logic over the PlanRepository / SessionRepository
ports — keeping it under `application` forced the plan_act flow (in
domain) to import application, breaking the layer direction. Existing
callers can keep importing from here.
"""

from app.domain.services.plan_service import PlanService

__all__ = ["PlanService"]
