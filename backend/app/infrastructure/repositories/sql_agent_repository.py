"""Postgres implementation of AgentRepository."""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.errors.exceptions import NotFoundError
from app.domain.models.agent import Agent
from app.domain.models.memory import Memory
from app.domain.repositories.agent_repository import AgentRepository
from app.infrastructure.models.sql import AgentRow

logger = logging.getLogger(__name__)


def _row_to_domain(row: AgentRow) -> Agent:
    memories: dict[str, Memory] = {}
    for key, raw in (row.memories or {}).items():
        try:
            memories[key] = Memory.model_validate(raw)
        except Exception:
            # Pre-rewrite memories used a different (langchain) message shape
            # and won't validate. Drop them rather than crash the agent.
            logger.warning("Discarding incompatible memory %s on agent %s", key, row.agent_id)
    return Agent(
        id=row.agent_id,
        model_name=row.model_name,
        temperature=row.temperature,
        max_tokens=row.max_tokens,
        memories=memories,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _domain_to_row(agent: Agent) -> AgentRow:
    return AgentRow(
        agent_id=agent.id,
        model_name=agent.model_name,
        temperature=agent.temperature,
        max_tokens=agent.max_tokens,
        memories={k: m.model_dump(mode="json") for k, m in agent.memories.items()},
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


class SqlAgentRepository(AgentRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, agent: Agent) -> None:
        async with self._session_factory() as session:
            row = await session.get(AgentRow, agent.id)
            if not row:
                session.add(_domain_to_row(agent))
            else:
                row.model_name = agent.model_name
                row.temperature = agent.temperature
                row.max_tokens = agent.max_tokens
                row.memories = {k: m.model_dump(mode="json") for k, m in agent.memories.items()}
            await session.commit()

    async def find_by_id(self, agent_id: str) -> Optional[Agent]:
        async with self._session_factory() as session:
            row = await session.get(AgentRow, agent_id)
            return _row_to_domain(row) if row else None

    async def add_memory(self, agent_id: str, name: str, memory: Memory) -> None:
        await self._upsert_memory(agent_id, name, memory)

    async def save_memory(self, agent_id: str, name: str, memory: Memory) -> None:
        await self._upsert_memory(agent_id, name, memory)

    async def _upsert_memory(self, agent_id: str, name: str, memory: Memory) -> None:
        async with self._session_factory() as session:
            row = await session.get(AgentRow, agent_id)
            if not row:
                raise NotFoundError(f"Agent {agent_id} not found")
            # Replace whole `memories` dict so SQLAlchemy detects the JSONB
            # change; column-level `onupdate=_utcnow` refreshes updated_at.
            new_memories = dict(row.memories or {})
            new_memories[name] = memory.model_dump(mode="json")
            row.memories = new_memories
            await session.commit()

    async def get_memory(self, agent_id: str, name: str) -> Memory:
        async with self._session_factory() as session:
            row = await session.get(AgentRow, agent_id)
            if not row:
                raise NotFoundError(f"Agent {agent_id} not found")
            stored = (row.memories or {}).get(name)
            if not stored:
                return Memory(messages=[])
            try:
                return Memory.model_validate(stored)
            except Exception:
                logger.warning(
                    "Discarding incompatible memory %s on agent %s", name, agent_id
                )
                return Memory(messages=[])
