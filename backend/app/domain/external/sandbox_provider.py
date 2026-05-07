"""Port for sandbox lifecycle management — the layer that decides
"which Sandbox does this session use, and is it still alive?".

The domain layer needs this contract so it can call into a sandbox
registry without importing the concrete `SandboxRegistry` from the
application layer (which would reverse the dependency direction).
The application layer's `SandboxRegistry` satisfies this Protocol
structurally — no inheritance needed.
"""

from typing import Optional, Protocol

from app.domain.external.sandbox import Sandbox
from app.domain.models.session import Session


class SandboxProvider(Protocol):
    """Resolves and recycles per-session sandboxes."""

    async def ensure_for(self, session: Session) -> Sandbox:
        """Return a verified-live sandbox bound to the given session,
        spawning a new container if the session has none or the bound
        one is dead."""
        ...

    async def ensure_for_session(self, session_id: str) -> Sandbox:
        """Same as `ensure_for`, but takes a session id instead of a
        loaded row. Implementations may load + verify the row before
        proceeding."""
        ...

    async def lookup_alive(self, session_id: str) -> Optional[Sandbox]:
        """Return the live sandbox or None — must NEVER spawn a new
        container. Used by polling endpoints (e.g. preview URL probe)
        where a write would race the chat-warmup path."""
        ...

    async def fetch_unmanaged(self, sandbox_id: str) -> Sandbox:
        """Get a Sandbox handle by container id without touching the
        registry's positive cache. For cleanup paths that need the
        handle to call `destroy()` and then forget it."""
        ...

    def invalidate(self, sandbox_id: str) -> None:
        """Drop the positive-cache entry for a sandbox id. Next ensure
        / lookup re-checks with the underlying runtime."""
        ...
