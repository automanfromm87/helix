from typing import Optional, Protocol, List
from datetime import datetime
from app.domain.models.session import Session, SessionStatus, SessionSummary
from app.domain.models.file import FileInfo
from app.domain.models.event import BaseEvent, MessageEvent

class SessionRepository(Protocol):
    """Repository interface for Session aggregate"""
    
    async def save(self, session: Session) -> None:
        """Save or update a session"""
        ...
    
    async def find_by_id(self, session_id: str) -> Optional[Session]:
        """Find a session by its ID"""
        ...
    
    async def find_by_user_id(self, user_id: str) -> List[Session]:
        """Find all sessions for a specific user"""
        ...
    
    async def find_summaries_by_user_id(self, user_id: str) -> List[SessionSummary]:
        """Find lightweight session summaries for a user (excludes events/files)"""
        ...
    
    async def find_by_id_and_user_id(self, session_id: str, user_id: str) -> Optional[Session]:
        """Find a session by ID and user ID (for authorization)"""
        ...

    async def find_events(
        self,
        session_id: str,
        before_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[BaseEvent]:
        """Cursor-paginated event fetch for a session.

        Returns up to `limit` events whose primary key is strictly LESS than
        `before_id` (or the latest `limit` events when None), ordered by
        ascending id so the caller can append them in chronological order.

        Used by the chat page to bound the initial network payload — long
        sessions previously sent every event back at once (8 MB+ in observed
        cases). Older events can be fetched on scroll-to-top with
        `before_id` set to the earliest currently-loaded id."""
        ...
    
    async def update_title(self, session_id: str, title: str) -> None:
        """Update the title of a session"""
        ...

    async def update_latest_message(self, session_id: str, message: str, timestamp: datetime) -> None:
        """Update the latest message of a session"""
        ...

    async def find_last_user_message(self, session_id: str) -> Optional[MessageEvent]:
        """Most recent user-role MessageEvent for the session, or None.

        Used by the auto-resume reaper to re-enqueue the user's last
        prompt after a backend crash / dev-mode reload, so the agent
        picks up where it left off without the user re-typing."""
        ...

    async def add_event(self, session_id: str, event: BaseEvent) -> None:
        """Add an event to a session"""
        ...
    
    async def add_file(self, session_id: str, file_info: FileInfo) -> None:
        """Add a file to a session"""
        ...
    
    async def remove_file(self, session_id: str, file_id: str) -> None:
        """Remove a file from a session"""
        ...

    async def get_file_by_path(self, session_id: str, file_path: str) -> Optional[FileInfo]:
        """Get file by path from a session"""
        ...

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        """Update the status of a session"""
        ...
    
    async def update_unread_message_count(self, session_id: str, count: int) -> None:
        """Update the unread message count of a session"""
        ...
    
    async def increment_unread_message_count(self, session_id: str) -> None:
        """Increment the unread message count of a session"""
        ...
    
    async def decrement_unread_message_count(self, session_id: str) -> None:
        """Decrement the unread message count of a session"""
        ...
    
    async def update_shared_status(self, session_id: str, is_shared: bool) -> None:
        """Update the shared status of a session"""
        ...

    async def update_project_id(self, session_id: str, project_id: Optional[str]) -> None:
        """Move a session into a project (or NULL to ungroup)"""
        ...

    async def update_workspace_summary(
        self, session_id: str, summary: Optional[str]
    ) -> None:
        """Replace the cached workspace markdown (or NULL to invalidate)."""
        ...

    async def delete(self, session_id: str) -> None:
        """Delete a session"""
        ...
    
    async def get_all(self) -> List[Session]:
        """Get all sessions"""
        ...

    async def search_summaries(
        self, user_id: str, query: str, limit: int = 50
    ) -> List[SessionSummary]:
        """Find sessions whose title / latest message / event payloads match `query`."""
        ...

    async def truncate_events_from(self, session_id: str, from_event_id: str) -> int:
        """Delete the event matching `from_event_id` and every later event.

        Used by regenerate: lops off everything from a chosen user message
        onwards so the agent re-runs from that point. Returns rows deleted.
        """
        ...

    async def delete_by_project_id(self, project_id: str, user_id: str) -> int:
        """Delete every session belonging to this project (and thus its events
        via CASCADE). Returns rows deleted."""
        ...

    async def list_in_flight_sessions(self) -> list[tuple[str, str]]:
        """Return (session_id, agent_id) pairs for sessions that were
        PENDING/RUNNING when the previous backend process died.

        Used by the startup recovery path to close dangling tool_uses and
        flip status to WAITING so the flow can resume on the next message.
        """
        ...

    async def mark_session_waiting(self, session_id: str) -> None:
        """Set session status to WAITING — used after crash recovery."""
        ...