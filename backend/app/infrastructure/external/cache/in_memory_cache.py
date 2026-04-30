"""In-memory Cache with TTL.

Single-process; values expire lazily on access. Pattern matching uses fnmatch
to mimic Redis-style globs.
"""

import asyncio
import fnmatch
import logging
from time import monotonic
from typing import Any, Dict, List, Optional, Tuple

from app.domain.external.cache import Cache

logger = logging.getLogger(__name__)


class InMemoryCache(Cache):
    def __init__(self) -> None:
        # value, expires_at (monotonic seconds, None = no expiry)
        self._store: Dict[str, Tuple[Any, Optional[float]]] = {}
        self._lock = asyncio.Lock()

    def _is_expired(self, expires_at: Optional[float]) -> bool:
        return expires_at is not None and monotonic() >= expires_at

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        expires_at = monotonic() + ttl if ttl is not None else None
        async with self._lock:
            self._store[key] = (value, expires_at)
        return True

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if self._is_expired(expires_at):
                del self._store[key]
                return None
            return value

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._store.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        return (await self.get(key)) is not None

    async def get_ttl(self, key: str) -> Optional[int]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            _, expires_at = entry
            if expires_at is None:
                return None
            remaining = expires_at - monotonic()
            if remaining <= 0:
                del self._store[key]
                return None
            return int(remaining)

    async def keys(self, pattern: str) -> List[str]:
        async with self._lock:
            now = monotonic()
            stale = [
                k for k, (_, exp) in self._store.items() if exp is not None and exp <= now
            ]
            for k in stale:
                del self._store[k]
            return [k for k in self._store if fnmatch.fnmatchcase(k, pattern)]

    async def clear_pattern(self, pattern: str) -> int:
        matching = await self.keys(pattern)
        async with self._lock:
            for k in matching:
                self._store.pop(k, None)
        return len(matching)
