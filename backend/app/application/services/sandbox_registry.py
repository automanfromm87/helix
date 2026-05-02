"""Single owner of sandbox lifecycle.

Why this exists. Pre-registry, `Sandbox.get` was `@alru_cache`d at the
class level. Every caller that asked for "the sandbox bound to session
X" would get the same `DockerSandbox` object indefinitely — even after
the underlying container had died (TTL self-shutdown, OOM, daemon
restart, manual `docker rm`). The cached object's `ip` and
`preview_host_port` pointed at a ghost; HTTP calls failed with
`ConnectError`, which `_resolve_or_recreate_sandbox` could never
upgrade into "respawn this thing" because `Sandbox.get` never raised
`SandboxUnavailableError` once it had a cache hit.

On top of that, recreate logic was scattered: chat-warmup
(`AgentDomainService._create_task`), file/shell/vnc handlers
(`_resolve_or_recreate_sandbox`), preview poll (`get_preview_url`),
fork bg-spawn (`fork_from_plan._spawn_sandbox_bg`) — four call sites,
each with their own decision about when to call `create`. With nothing
serializing them, two parallel requests for a freshly-dead sandbox
would each call `Sandbox.create`, leaving an orphan container whose
session row got immediately overwritten by the loser of the race.

This registry replaces all of that with one entry point per intent:

  - `ensure_for_session(session_id)` — return a verified-live sandbox,
    spawning if needed. Per-session lock guarantees at most one
    outstanding create. Used by chat-warmup, file/shell/vnc, anywhere
    the caller actively wants the sandbox to exist.

  - `lookup_alive(session_id)` — pure read; returns the live sandbox
    or None. Used by GET /preview where polling-driven create would
    fight chat-warmup's create. Verifies via `Sandbox.fetch`.

  - `invalidate(sandbox_id)` — drop the positive-cache entry; useful
    after explicit destroys.

The cache is a small TTL'd dict keyed by sandbox_id (not session_id —
multiple sessions could in principle share, and invalidation comes
from "container X died" events, which are sandbox-scoped). TTL is
short (10s default): long enough that hot paths (file tree refresh,
preview poll, plan list) don't hammer `docker inspect`, short enough
that a container that died out-of-band surfaces in <10s rather than
"never until backend restart" like the old alru_cache.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.application.errors.exceptions import (
    NotFoundError,
    SandboxUnavailableError,
)
from app.domain.external.sandbox import Sandbox
from app.domain.models.session import Session
from app.domain.repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    """A positive-cache record: a sandbox handle plus when we last
    confirmed via `Sandbox.fetch` that its container is real. The
    `verified_at` clock is `time.monotonic` so wall-clock jumps
    (NTP drift, container restart) don't break TTL math.
    """

    sandbox: Sandbox
    verified_at: float = field(default_factory=time.monotonic)

    def fresh(self, ttl: float) -> bool:
        return (time.monotonic() - self.verified_at) < ttl


class SandboxRegistry:
    def __init__(
        self,
        sandbox_cls: type[Sandbox],
        session_repository: SessionRepository,
        *,
        verify_ttl_seconds: float = 10.0,
    ) -> None:
        self._sandbox_cls = sandbox_cls
        self._session_repository = session_repository
        self._verify_ttl = verify_ttl_seconds
        self._cache: dict[str, _Entry] = {}
        # Per-session locks dedup concurrent ensure() calls. Held only
        # for the duration of fetch-or-create; the read-only fast path
        # never touches it. We lazily create the lock to avoid leaking
        # memory for sessions that never open a sandbox.
        self._session_locks: dict[str, asyncio.Lock] = {}
        # Guards `_session_locks` itself. Held microscopically — just
        # the dict lookup/insert. Using a module-level lock here would
        # serialize all sessions; this nested-lock pattern keeps the
        # contention scope small.
        self._registry_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def ensure_for_session(self, session_id: str) -> Sandbox:
        """Return a verified-live sandbox bound to `session_id`. Spawns
        a new container if the session has none, or if the bound one
        is dead. Raises `NotFoundError` if the session row itself is
        missing.
        """
        session = await self._session_repository.find_by_id(session_id)
        if session is None:
            raise NotFoundError(f"Session {session_id} not found")
        return await self.ensure_for(session)

    async def ensure_for(self, session: Session) -> Sandbox:
        """Same as `ensure_for_session`, but skips the DB read when the
        caller already has the row. The hot paths (chat-warmup,
        file_view) usually do — handing the row through avoids a
        roundtrip per request.
        """
        # Fast path — recent successful verification. Lock-free.
        if session.sandbox_id:
            cached = self._cache.get(session.sandbox_id)
            if cached and cached.fresh(self._verify_ttl):
                return cached.sandbox

        lock = await self._lock_for(session.id)
        async with lock:
            # Re-read the session row inside the critical section. The
            # caller's `session` may be stale if another coroutine just
            # rebound `sandbox_id` (e.g. background fork-spawn raced
            # with this user-driven call).
            fresh_session = await self._session_repository.find_by_id(session.id)
            if fresh_session is not None:
                session = fresh_session

            if session.sandbox_id:
                cached = self._cache.get(session.sandbox_id)
                if cached and cached.fresh(self._verify_ttl):
                    return cached.sandbox
                try:
                    sandbox = await self._sandbox_cls.fetch(session.sandbox_id)
                except SandboxUnavailableError:
                    logger.info(
                        "session=%s sandbox=%s gone, respawning",
                        session.id, session.sandbox_id,
                    )
                    self._cache.pop(session.sandbox_id, None)
                else:
                    self._cache[session.sandbox_id] = _Entry(sandbox)
                    return sandbox

            # Either no sandbox bound, or the bound one is dead.
            sandbox = await self._sandbox_cls.create(session_id=session.id)
            session.sandbox_id = sandbox.id
            await self._session_repository.save(session)
            self._cache[sandbox.id] = _Entry(sandbox)
            logger.info("session=%s sandbox=%s created", session.id, sandbox.id)
            return sandbox

    async def lookup_alive(self, session_id: str) -> Optional[Sandbox]:
        """Return the live sandbox or None — no spawn.

        Used by GET /preview: polling that the iframe sends every few
        seconds while the dev server warms up. Spawning on poll would
        race with chat-warmup's spawn (both miss cache → both call
        `Sandbox.create` → orphan container, last-write-wins on
        `session.sandbox_id`). Polling should never be a write-trigger.
        """
        session = await self._session_repository.find_by_id(session_id)
        if session is None or not session.sandbox_id:
            return None

        cached = self._cache.get(session.sandbox_id)
        if cached and cached.fresh(self._verify_ttl):
            return cached.sandbox
        try:
            sandbox = await self._sandbox_cls.fetch(session.sandbox_id)
        except SandboxUnavailableError:
            self._cache.pop(session.sandbox_id, None)
            return None
        self._cache[session.sandbox_id] = _Entry(sandbox)
        return sandbox

    async def fetch_unmanaged(self, sandbox_id: str) -> Sandbox:
        """Get a Sandbox handle by container ID without binding it to
        any session — for cleanup paths (destroy on session delete)
        where we already have the id but don't want to touch the
        registry's positive cache. Raises `SandboxUnavailableError` if
        the container is gone (caller treats that as "already cleaned
        up, move on").
        """
        return await self._sandbox_cls.fetch(sandbox_id)

    def invalidate(self, sandbox_id: str) -> None:
        """Drop the positive-cache entry. Next ensure/lookup re-checks
        with the docker daemon. Call this after an explicit destroy or
        when an out-of-band signal (e.g. webhook, container event
        stream) tells you the container is gone.
        """
        self._cache.pop(sandbox_id, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._registry_lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            return lock
