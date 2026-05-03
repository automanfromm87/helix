from fastapi import APIRouter

from . import (
    auth_routes,
    config_routes,
    file_routes,
    plan_routes,
    project_routes,
    session_context_routes,
    session_routes,
    session_sandbox_routes,
    session_share_routes,
    skill_routes,
    stats_routes,
)


def create_api_router() -> APIRouter:
    """Create and configure the main API router."""
    api_router = APIRouter()

    api_router.include_router(session_routes.router)
    # Session feature splits — same `/sessions` prefix, registered as
    # separate routers so each module owns its own concern.
    api_router.include_router(session_sandbox_routes.router)
    api_router.include_router(session_context_routes.router)
    api_router.include_router(session_share_routes.router)

    api_router.include_router(file_routes.router)
    api_router.include_router(auth_routes.router)
    api_router.include_router(config_routes.router)
    api_router.include_router(project_routes.router)
    api_router.include_router(skill_routes.router)
    api_router.include_router(stats_routes.router)
    api_router.include_router(plan_routes.router)

    return api_router


router = create_api_router()