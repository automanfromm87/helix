from typing import Optional, Union
import logging
from functools import lru_cache
from fastapi import Request, HTTPException, status, Depends, Query
from starlette.websockets import WebSocket
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.domain.external.file import FileStorage
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.plan_repository import PlanRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.session_repository import SessionRepository
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.external.search import get_search_engine
from app.domain.models.user import User, UserRole
from app.application.errors.exceptions import UnauthorizedError
from app.core.config import get_settings

# Application services
from app.application.services.agent_service import AgentService
from app.application.services.file_service import FileService
from app.application.services.auth_service import AuthService
from app.application.services.token_service import TokenService
from app.application.services.email_service import EmailService
from app.application.services.project_service import ProjectService
from app.application.services.plan_service import PlanService
from app.infrastructure.external.cache import get_cache

# Sandbox + task execution
from app.infrastructure.external.sandbox.factory import get_sandbox_cls
from app.infrastructure.external.task.in_memory_task import InMemoryTask
from app.infrastructure.repositories.file_mcp_repository import FileMCPRepository
from app.infrastructure.repositories.sql_skill_repository import SqlSkillRepository
from app.infrastructure.skills.file_skill_repository import FileSkillRepository

# Postgres-backed implementations
from app.infrastructure.external.file.sql_file_storage import SqlFileStorage
from app.infrastructure.repositories.sql_agent_repository import SqlAgentRepository
from app.infrastructure.repositories.sql_plan_repository import SqlPlanRepository
from app.infrastructure.repositories.sql_project_repository import SqlProjectRepository
from app.infrastructure.repositories.sql_session_repository import SqlSessionRepository
from app.infrastructure.repositories.sql_user_repository import SqlUserRepository
from app.infrastructure.storage.postgres import get_postgres

logger = logging.getLogger(__name__)

security_bearer = HTTPBearer(auto_error=False)


@lru_cache()
def get_agent_repository() -> AgentRepository:
    return SqlAgentRepository(get_postgres().session_factory)


@lru_cache()
def get_session_repository() -> SessionRepository:
    return SqlSessionRepository(get_postgres().session_factory)


@lru_cache()
def get_user_repository() -> UserRepository:
    return SqlUserRepository(get_postgres().session_factory)


@lru_cache()
def get_project_repository() -> ProjectRepository:
    return SqlProjectRepository(get_postgres().session_factory)


@lru_cache()
def get_project_service() -> ProjectService:
    return ProjectService(
        project_repository=get_project_repository(),
        session_repository=get_session_repository(),
    )


@lru_cache()
def get_plan_repository() -> PlanRepository:
    return SqlPlanRepository(get_postgres().session_factory)


@lru_cache()
def get_plan_service() -> PlanService:
    return PlanService(
        plan_repository=get_plan_repository(),
        session_repository=get_session_repository(),
    )


@lru_cache()
def get_file_storage() -> FileStorage:
    return SqlFileStorage(get_postgres().session_factory)


@lru_cache()
def get_skill_repository() -> FileSkillRepository:
    return FileSkillRepository()


@lru_cache()
def get_skill_store() -> SqlSkillRepository:
    return SqlSkillRepository(get_postgres().session_factory)


@lru_cache()
def get_sandbox_registry() -> "SandboxRegistry":
    """Process-wide singleton. Both AgentService and AgentDomainService
    must share the same instance — distinct registries would defeat the
    per-session lock (each would think it's the only one creating).
    """
    from app.application.services.sandbox_registry import SandboxRegistry

    logger.info("Creating SandboxRegistry instance")
    return SandboxRegistry(
        sandbox_cls=get_sandbox_cls(),
        session_repository=get_session_repository(),
    )


@lru_cache()
def get_agent_service() -> AgentService:
    logger.info("Creating AgentService instance")
    return AgentService(
        agent_repository=get_agent_repository(),
        session_repository=get_session_repository(),
        sandbox_cls=get_sandbox_cls(),
        task_cls=InMemoryTask,
        file_storage=get_file_storage(),
        search_engine=get_search_engine(),
        mcp_repository=FileMCPRepository(),
        plan_repository=get_plan_repository(),
        project_repository=get_project_repository(),
        skill_repository=get_skill_repository(),
        skill_store=get_skill_store(),
        sandbox_registry=get_sandbox_registry(),
    )


@lru_cache()
def get_file_service() -> FileService:
    logger.info("Creating FileService instance")
    return FileService(
        file_storage=get_file_storage(),
        token_service=get_token_service(),
    )


@lru_cache()
def get_auth_service() -> AuthService:
    logger.info("Creating AuthService instance")
    return AuthService(
        user_repository=get_user_repository(),
        token_service=get_token_service(),
    )


@lru_cache()
def get_token_service() -> TokenService:
    logger.info("Creating TokenService instance")
    return TokenService()


@lru_cache()
def get_email_service() -> EmailService:
    logger.info("Creating EmailService instance")
    return EmailService(cache=get_cache())


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------


def _anonymous_user() -> User:
    return User(
        id="anonymous",
        fullname="anonymous",
        email="anonymous@localhost",
        role=UserRole.USER,
        is_active=True,
    )


async def get_current_user(
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    if get_settings().auth_provider == "none":
        return _anonymous_user()
    if not bearer_credentials:
        raise UnauthorizedError("Authentication required")
    user = await auth_service.verify_token(bearer_credentials.credentials)
    if not user:
        raise UnauthorizedError("Invalid token")
    if not user.is_active:
        raise UnauthorizedError("User account is inactive")
    return user


async def get_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != UserRole.ADMIN:
        raise UnauthorizedError("Admin access required")
    return current_user


async def get_optional_current_user(
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    auth_service: AuthService = Depends(get_auth_service),
) -> Optional[User]:
    if get_settings().auth_provider == "none":
        return _anonymous_user()
    if not bearer_credentials:
        return None
    user = await auth_service.verify_token(bearer_credentials.credentials)
    if user and user.is_active:
        return user
    return None


async def verify_signature(
    request: Request,
    signature: Optional[str] = Query(None),
    token_service: TokenService = Depends(get_token_service),
) -> str:
    return await _verify_signature(request, signature, token_service)


async def verify_signature_websocket(
    request: WebSocket,
    signature: Optional[str] = Query(None),
    token_service: TokenService = Depends(get_token_service),
) -> str:
    return await _verify_signature(request, signature, token_service)


async def _verify_signature(
    request: Union[Request, WebSocket],
    signature: Optional[str] = Query(None),
    token_service: TokenService = Depends(get_token_service),
) -> str:
    if not signature:
        logger.error(f"Missing signature: {request.url}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing signature")
    if not token_service.verify_signed_url(str(request.url)):
        logger.error(f"Invalid signature: {request.url}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    return signature
