"""Postgres implementation of UserRepository."""

import logging
from typing import List, Optional

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.errors.exceptions import NotFoundError
from app.domain.models.user import User, UserRole
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.models.sql import UserRow

logger = logging.getLogger(__name__)


def _row_to_domain(row: UserRow) -> User:
    return User(
        id=row.user_id,
        fullname=row.fullname,
        email=row.email,
        password_hash=row.password_hash,
        role=UserRole(row.role),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_login_at=row.last_login_at,
    )


def _domain_to_row(user: User) -> UserRow:
    return UserRow(
        user_id=user.id,
        fullname=user.fullname,
        email=user.email.lower(),
        password_hash=user.password_hash,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


class SqlUserRepository(UserRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_user(self, user: User) -> User:
        async with self._session_factory() as session:
            row = _domain_to_row(user)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _row_to_domain(row)

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        async with self._session_factory() as session:
            row = await session.get(UserRow, user_id)
            return _row_to_domain(row) if row else None

    async def get_user_by_fullname(self, fullname: str) -> Optional[User]:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserRow).where(UserRow.fullname == fullname)
            )
            return _row_to_domain(row) if row else None

    async def get_user_by_email(self, email: str) -> Optional[User]:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserRow).where(UserRow.email == email.lower())
            )
            return _row_to_domain(row) if row else None

    async def update_user(self, user: User) -> User:
        async with self._session_factory() as session:
            row = await session.get(UserRow, user.id)
            if not row:
                raise NotFoundError(f"User not found: {user.id}")
            row.fullname = user.fullname
            row.email = user.email.lower()
            row.password_hash = user.password_hash
            row.role = user.role.value
            row.is_active = user.is_active
            row.last_login_at = user.last_login_at
            # updated_at handled by onupdate=_utcnow
            await session.commit()
            await session.refresh(row)
            return _row_to_domain(row)

    async def delete_user(self, user_id: str) -> bool:
        async with self._session_factory() as session:
            row = await session.get(UserRow, user_id)
            if not row:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def list_users(self, limit: int = 100, offset: int = 0) -> List[User]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(UserRow).order_by(UserRow.created_at.desc()).limit(limit).offset(offset)
            )
            return [_row_to_domain(r) for r in result.scalars().all()]

    async def fullname_exists(self, fullname: str) -> bool:
        async with self._session_factory() as session:
            return bool(
                await session.scalar(
                    select(exists().where(UserRow.fullname == fullname))
                )
            )

    async def email_exists(self, email: str) -> bool:
        async with self._session_factory() as session:
            return bool(
                await session.scalar(
                    select(exists().where(UserRow.email == email.lower()))
                )
            )
