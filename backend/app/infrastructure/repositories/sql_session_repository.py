"""Postgres implementation of SessionRepository.

The events array is split into a dedicated `session_events` table so that
appending an event is a constant-time INSERT rather than rewriting the
session row.
"""

import logging
from datetime import datetime
from typing import Any, List, Optional

from pydantic import TypeAdapter
from sqlalchemy import String, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.application.errors.exceptions import NotFoundError
from app.domain.models.event import AgentEvent, BaseEvent, MessageEvent
from app.domain.models.file import FileInfo
from app.domain.models.session import (
    ContextFile,
    Session,
    SessionStatus,
    SessionSummary,
)
from app.domain.repositories.session_repository import SessionRepository
from app.infrastructure.models.sql import (
    SessionContextFileRow,
    SessionEventRow,
    SessionRow,
)

logger = logging.getLogger(__name__)

# Build the discriminated-union adapter once. Rebuilding it per row showed up
# as a hot-path cost when replaying long sessions.
_AGENT_EVENT_ADAPTER: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)


def _events_from_rows(rows: List[SessionEventRow]) -> List[AgentEvent]:
    """Reconstruct typed AgentEvent objects from JSON rows.

    AgentEvent is a Pydantic discriminated union — re-validating the dict
    payload restores the correct concrete subclass (PlanEvent, ToolEvent, …).
    """
    result: List[AgentEvent] = []
    for r in rows:
        try:
            result.append(_AGENT_EVENT_ADAPTER.validate_python(r.event_data))
        except Exception:
            logger.exception("Failed to re-validate event id=%s", r.id)
    return result


def _row_to_domain(row: SessionRow, events: List[AgentEvent]) -> Session:
    files = [FileInfo.model_validate(f) for f in (row.files or [])]
    return Session(
        id=row.session_id,
        user_id=row.user_id,
        project_id=row.project_id,
        system_prompt=row.system_prompt,
        workspace_summary=row.workspace_summary,
        sandbox_id=row.sandbox_id,
        agent_id=row.agent_id,
        task_id=row.task_id,
        title=row.title,
        unread_message_count=row.unread_message_count,
        latest_message=row.latest_message,
        latest_message_at=row.latest_message_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        events=events,
        files=files,
        status=SessionStatus(row.status),
        is_shared=row.is_shared,
        retrieval_only_context=row.retrieval_only_context,
    )


def _new_session_row(session: Session) -> SessionRow:
    return SessionRow(
        session_id=session.id,
        user_id=session.user_id,
        project_id=session.project_id,
        system_prompt=session.system_prompt,
        workspace_summary=session.workspace_summary,
        sandbox_id=session.sandbox_id,
        agent_id=session.agent_id,
        task_id=session.task_id,
        title=session.title,
        status=session.status.value,
        unread_message_count=session.unread_message_count,
        latest_message=session.latest_message,
        latest_message_at=session.latest_message_at,
        is_shared=session.is_shared,
        retrieval_only_context=session.retrieval_only_context,
        files=[f.model_dump(mode="json") for f in session.files],
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


class SqlSessionRepository(SessionRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _apply_update(self, session_id: str, **values: Any) -> None:
        """Single-column UPDATE that 404s if the row is missing.

        `updated_at` is not set here — the column's `onupdate=_utcnow`
        handles it whenever any tracked column changes.
        """
        async with self._session_factory() as db:
            result = await db.execute(
                update(SessionRow).where(SessionRow.session_id == session_id).values(**values)
            )
            if result.rowcount == 0:
                raise NotFoundError(f"Session {session_id} not found")
            await db.commit()

    async def _load_with_events(
        self, db: AsyncSession, *whereclauses: Any
    ) -> Optional[SessionRow]:
        """Fetch one SessionRow with its events eagerly loaded (avoids N+1)."""
        stmt = (
            select(SessionRow)
            .options(selectinload(SessionRow.events))
            .where(*whereclauses)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(self, session: Session) -> None:
        async with self._session_factory() as db:
            row = await db.get(SessionRow, session.id)
            if not row:
                db.add(_new_session_row(session))
                for event in session.events:
                    db.add(
                        SessionEventRow(
                            session_id=session.id,
                            event_type=event.type,
                            event_data=event.model_dump(mode="json"),
                        )
                    )
            else:
                row.user_id = session.user_id
                row.project_id = session.project_id
                row.system_prompt = session.system_prompt
                row.workspace_summary = session.workspace_summary
                row.sandbox_id = session.sandbox_id
                row.agent_id = session.agent_id
                row.task_id = session.task_id
                row.title = session.title
                row.status = session.status.value
                row.unread_message_count = session.unread_message_count
                row.latest_message = session.latest_message
                row.latest_message_at = session.latest_message_at
                row.is_shared = session.is_shared
                row.retrieval_only_context = session.retrieval_only_context
                row.files = [f.model_dump(mode="json") for f in session.files]
            await db.commit()

    async def find_by_id(self, session_id: str) -> Optional[Session]:
        async with self._session_factory() as db:
            row = await self._load_with_events(db, SessionRow.session_id == session_id)
            if not row:
                return None
            return _row_to_domain(row, _events_from_rows(list(row.events)))

    async def find_by_user_id(self, user_id: str) -> List[Session]:
        async with self._session_factory() as db:
            stmt = (
                select(SessionRow)
                .options(selectinload(SessionRow.events))
                .where(SessionRow.user_id == user_id)
                .order_by(SessionRow.latest_message_at.desc())
            )
            result = await db.execute(stmt)
            return [
                _row_to_domain(row, _events_from_rows(list(row.events)))
                for row in result.scalars().all()
            ]

    async def find_summaries_by_user_id(self, user_id: str) -> List[SessionSummary]:
        async with self._session_factory() as db:
            result = await db.execute(
                select(
                    SessionRow.session_id,
                    SessionRow.user_id,
                    SessionRow.project_id,
                    SessionRow.title,
                    SessionRow.unread_message_count,
                    SessionRow.latest_message,
                    SessionRow.latest_message_at,
                    SessionRow.status,
                    SessionRow.is_shared,
                )
                .where(SessionRow.user_id == user_id)
                .order_by(SessionRow.latest_message_at.desc())
            )
            return [
                SessionSummary(
                    id=r.session_id,
                    user_id=r.user_id,
                    project_id=r.project_id,
                    title=r.title,
                    unread_message_count=r.unread_message_count,
                    latest_message=r.latest_message,
                    latest_message_at=r.latest_message_at,
                    status=SessionStatus(r.status),
                    is_shared=r.is_shared,
                )
                for r in result.all()
            ]

    async def find_by_id_and_user_id(
        self, session_id: str, user_id: str
    ) -> Optional[Session]:
        async with self._session_factory() as db:
            row = await self._load_with_events(
                db,
                SessionRow.session_id == session_id,
                SessionRow.user_id == user_id,
            )
            if not row:
                return None
            return _row_to_domain(row, _events_from_rows(list(row.events)))

    async def find_events(
        self,
        session_id: str,
        before_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AgentEvent]:
        # Latest `limit` events strictly before the cursor (or the global
        # latest when no cursor). The PK is BigInt autoincrement, but FE
        # sees event.id as the queue-counter string in event_data — we
        # resolve the cursor by matching that field. This costs one extra
        # subquery per page; cheap given the limit on result size.
        from sqlalchemy import and_, desc

        async with self._session_factory() as db:
            stmt = select(SessionEventRow).where(
                SessionEventRow.session_id == session_id
            )
            if before_id:
                cutoff = await db.scalar(
                    select(SessionEventRow.id)
                    .where(
                        and_(
                            SessionEventRow.session_id == session_id,
                            SessionEventRow.event_data["id"].astext == before_id,
                        )
                    )
                    .limit(1)
                )
                if cutoff is not None:
                    stmt = stmt.where(SessionEventRow.id < cutoff)
            stmt = stmt.order_by(desc(SessionEventRow.id)).limit(int(limit))
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
        # Caller wants ascending chronological order — DB returned newest-first
        # so we can apply the limit cleanly; reverse for output.
        rows.reverse()
        return _events_from_rows(rows)

    async def update_title(self, session_id: str, title: str) -> None:
        await self._apply_update(session_id, title=title)

    async def update_latest_message(
        self, session_id: str, message: str, timestamp: datetime
    ) -> None:
        await self._apply_update(
            session_id, latest_message=message, latest_message_at=timestamp
        )

    async def find_last_user_message(self, session_id: str) -> Optional[MessageEvent]:
        async with self._session_factory() as db:
            row = await db.scalar(
                select(SessionEventRow)
                .where(
                    SessionEventRow.session_id == session_id,
                    SessionEventRow.event_type == "message",
                    SessionEventRow.event_data["role"].astext == "user",
                )
                .order_by(SessionEventRow.id.desc())
                .limit(1)
            )
            if row is None:
                return None
            try:
                return MessageEvent.model_validate(row.event_data)
            except Exception:
                logger.warning(
                    "Discarding malformed user MessageEvent in session %s", session_id,
                )
                return None

    async def add_event(self, session_id: str, event: BaseEvent) -> None:
        async with self._session_factory() as db:
            row = await db.get(SessionRow, session_id)
            if not row:
                raise NotFoundError(f"Session {session_id} not found")
            db.add(
                SessionEventRow(
                    session_id=session_id,
                    event_type=event.type,
                    event_data=event.model_dump(mode="json"),
                )
            )
            # `onupdate` only fires when a tracked column on SessionRow changes;
            # appending a child SessionEventRow alone won't trigger it.
            row.updated_at = row.updated_at
            await db.commit()

    async def add_file(self, session_id: str, file_info: FileInfo) -> None:
        async with self._session_factory() as db:
            row = await db.get(SessionRow, session_id)
            if not row:
                raise NotFoundError(f"Session {session_id} not found")
            row.files = [*(row.files or []), file_info.model_dump(mode="json")]
            await db.commit()

    async def remove_file(self, session_id: str, file_id: str) -> None:
        async with self._session_factory() as db:
            row = await db.get(SessionRow, session_id)
            if not row:
                raise NotFoundError(f"Session {session_id} not found")
            row.files = [f for f in (row.files or []) if f.get("file_id") != file_id]
            await db.commit()

    async def add_context_file(self, session_id: str, file: ContextFile) -> None:
        async with self._session_factory() as db:
            # Insert the row, scoped under the session FK so a session
            # delete cascades it. We don't pre-check for duplicates by
            # filename — multiple uploads of the same name are common
            # (different revisions of a spec); the user can delete the
            # stale one if it matters.
            db.add(
                SessionContextFileRow(
                    id=file.id,
                    session_id=session_id,
                    filename=file.filename,
                    content=file.content,
                    size=file.size,
                    created_at=file.created_at,
                )
            )
            await db.commit()

    async def list_context_files(self, session_id: str) -> List[ContextFile]:
        async with self._session_factory() as db:
            result = await db.execute(
                select(SessionContextFileRow)
                .where(SessionContextFileRow.session_id == session_id)
                .order_by(SessionContextFileRow.created_at.asc())
            )
            return [
                ContextFile(
                    id=r.id,
                    filename=r.filename,
                    content=r.content,
                    size=r.size,
                    created_at=r.created_at,
                )
                for r in result.scalars().all()
            ]

    async def remove_context_file(self, session_id: str, file_id: str) -> bool:
        async with self._session_factory() as db:
            result = await db.execute(
                delete(SessionContextFileRow).where(
                    SessionContextFileRow.session_id == session_id,
                    SessionContextFileRow.id == file_id,
                )
            )
            await db.commit()
            return (result.rowcount or 0) > 0

    async def get_file_by_path(
        self, session_id: str, file_path: str
    ) -> Optional[FileInfo]:
        async with self._session_factory() as db:
            row = await db.get(SessionRow, session_id)
            if not row:
                raise NotFoundError(f"Session {session_id} not found")
            for f in row.files or []:
                if f.get("file_path") == file_path:
                    return FileInfo.model_validate(f)
            return None

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        await self._apply_update(session_id, status=status.value)

    async def update_unread_message_count(self, session_id: str, count: int) -> None:
        await self._apply_update(session_id, unread_message_count=count)

    async def increment_unread_message_count(self, session_id: str) -> None:
        await self._apply_update(
            session_id, unread_message_count=SessionRow.unread_message_count + 1
        )

    async def decrement_unread_message_count(self, session_id: str) -> None:
        await self._apply_update(
            session_id, unread_message_count=SessionRow.unread_message_count - 1
        )

    async def update_shared_status(self, session_id: str, is_shared: bool) -> None:
        await self._apply_update(session_id, is_shared=is_shared)

    async def update_project_id(self, session_id: str, project_id: Optional[str]) -> None:
        await self._apply_update(session_id, project_id=project_id)

    async def update_workspace_summary(
        self, session_id: str, summary: Optional[str]
    ) -> None:
        await self._apply_update(session_id, workspace_summary=summary)

    async def delete(self, session_id: str) -> None:
        async with self._session_factory() as db:
            row = await db.get(SessionRow, session_id)
            if row:
                # session_events ON DELETE CASCADE handles its rows automatically
                await db.delete(row)
                await db.commit()

    async def get_all(self) -> List[Session]:
        async with self._session_factory() as db:
            stmt = (
                select(SessionRow)
                .options(selectinload(SessionRow.events))
                .order_by(SessionRow.latest_message_at.desc())
            )
            result = await db.execute(stmt)
            return [
                _row_to_domain(row, _events_from_rows(list(row.events)))
                for row in result.scalars().all()
            ]

    async def truncate_events_from(self, session_id: str, from_event_id: str) -> int:
        """Delete the event whose payload `id` field equals `from_event_id`,
        plus every later event in the same session."""
        async with self._session_factory() as db:
            # Find the row whose event_data.id matches the user-facing event id.
            anchor = await db.scalar(
                select(SessionEventRow.id)
                .where(
                    SessionEventRow.session_id == session_id,
                    SessionEventRow.event_data["id"].astext == from_event_id,
                )
                .limit(1)
            )
            if anchor is None:
                return 0
            result = await db.execute(
                delete(SessionEventRow).where(
                    SessionEventRow.session_id == session_id,
                    SessionEventRow.id >= anchor,
                )
            )
            await db.commit()
            return result.rowcount or 0

    async def search_summaries(
        self, user_id: str, query: str, limit: int = 50
    ) -> List[SessionSummary]:
        """ILIKE on title + latest_message; for events the JSONB is cast to text
        so the same SQL works for any event payload shape. For larger corpora
        swap to a tsvector index on event_data."""
        like = f"%{query}%"
        async with self._session_factory() as db:
            # Match against session row, plus any event whose JSON contains the
            # query string. DISTINCT keeps the result stable when many events
            # match.
            event_match_subq = (
                select(SessionEventRow.session_id)
                .where(SessionEventRow.event_data.cast(String).ilike(like))
                .distinct()
                .subquery()
            )
            stmt = (
                select(SessionRow)
                .where(
                    SessionRow.user_id == user_id,
                    or_(
                        SessionRow.title.ilike(like),
                        SessionRow.latest_message.ilike(like),
                        SessionRow.session_id.in_(select(event_match_subq.c.session_id)),
                    ),
                )
                .order_by(SessionRow.latest_message_at.desc())
                .limit(limit)
            )
            result = await db.execute(stmt)
            return [
                SessionSummary(
                    id=r.session_id,
                    user_id=r.user_id,
                    project_id=r.project_id,
                    title=r.title,
                    unread_message_count=r.unread_message_count,
                    latest_message=r.latest_message,
                    latest_message_at=r.latest_message_at,
                    status=SessionStatus(r.status),
                    is_shared=r.is_shared,
                )
                for r in result.scalars().all()
            ]

    async def delete_by_project_id(self, project_id: str, user_id: str) -> int:
        async with self._session_factory() as db:
            result = await db.execute(
                delete(SessionRow).where(
                    SessionRow.project_id == project_id,
                    SessionRow.user_id == user_id,
                )
            )
            await db.commit()
            return result.rowcount or 0

    async def find_ids_and_sandbox_by_project_id(
        self, project_id: str, user_id: str
    ) -> list[tuple[str, Optional[str]]]:
        """Returns [(session_id, sandbox_id), ...] — used by cleanup paths
        that need to destroy sandbox containers + bind-mount dirs before
        the bulk DB delete drops the rows."""
        async with self._session_factory() as db:
            result = await db.execute(
                select(SessionRow.session_id, SessionRow.sandbox_id).where(
                    SessionRow.project_id == project_id,
                    SessionRow.user_id == user_id,
                )
            )
            return [(r.session_id, r.sandbox_id) for r in result.all()]

    async def list_in_flight_sessions(self) -> list[tuple[str, str]]:
        """Return (session_id, agent_id) pairs for sessions that were active
        when the previous backend process died — used by the startup
        recovery path to close dangling tool_uses and flip status.

        INTERRUPTED is included: the previous run hit an unhandled exception,
        but the user never asked to stop. After whatever caused the failure
        is fixed (e.g. a hot-reload bug), the next backend boot reattaches
        and re-enqueues the last user message.
        """
        active = (
            SessionStatus.PENDING.value,
            SessionStatus.RUNNING.value,
            SessionStatus.INTERRUPTED.value,
        )
        async with self._session_factory() as db:
            result = await db.execute(
                select(SessionRow.session_id, SessionRow.agent_id).where(
                    SessionRow.status.in_(active)
                )
            )
            return [(sid, aid) for sid, aid in result.all()]

    async def mark_session_waiting(self, session_id: str) -> None:
        """Flip a session's status to WAITING — used after recovery so the
        flow's resume branch picks it up on the user's next message."""
        async with self._session_factory() as db:
            await db.execute(
                update(SessionRow)
                .where(SessionRow.session_id == session_id)
                .values(status=SessionStatus.WAITING.value)
            )
            await db.commit()

    async def get_known_sandbox_ids(self) -> set[str]:
        """All non-null sandbox_ids regardless of session status (for startup reaper)."""
        async with self._session_factory() as db:
            result = await db.execute(
                select(SessionRow.sandbox_id).where(SessionRow.sandbox_id.is_not(None))
            )
            return {sid for (sid,) in result.all() if sid}

    async def get_active_sandbox_ids(self) -> set[str]:
        """Sandbox_ids whose session is still active (for janitor)."""
        active = (
            SessionStatus.PENDING.value,
            SessionStatus.RUNNING.value,
            SessionStatus.WAITING.value,
            SessionStatus.INTERRUPTED.value,
        )
        async with self._session_factory() as db:
            result = await db.execute(
                select(SessionRow.sandbox_id).where(
                    SessionRow.sandbox_id.is_not(None),
                    SessionRow.status.in_(active),
                )
            )
            return {sid for (sid,) in result.all() if sid}
