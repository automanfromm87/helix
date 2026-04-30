"""In-memory MessageQueue.

Replaces the Redis-backed implementation. Helix runs in a single backend
process so cross-process delivery isn't required — an `asyncio.Event`-driven
list is enough for both FIFO consumption (input streams) and replay-from-
position consumption (output streams).
"""

import asyncio
from typing import Any, AsyncGenerator, List, Optional, Tuple

from app.domain.external.message_queue import MessageQueue


class InMemoryQueue(MessageQueue):
    """Append-only list with monotonically increasing IDs and async fan-out."""

    def __init__(self) -> None:
        self._items: List[Tuple[str, Any]] = []
        # Bumped on every put so any waiter can wake and re-check.
        self._cond = asyncio.Condition()
        self._counter = 0

    async def put(self, message: Any) -> str:
        async with self._cond:
            self._counter += 1
            msg_id = f"{self._counter:020d}"
            self._items.append((msg_id, message))
            self._cond.notify_all()
        return msg_id

    async def get(
        self, start_id: Optional[str] = None, block_ms: Optional[int] = None
    ) -> Tuple[Optional[str], Optional[Any]]:
        """Return the first item with id > start_id, optionally blocking."""

        def _pick() -> Tuple[Optional[str], Optional[Any]]:
            for mid, msg in self._items:
                if start_id is None or mid > start_id:
                    return mid, msg
            return None, None

        mid, msg = _pick()
        if mid is not None or block_ms is None:
            return mid, msg

        # Match Redis semantics: block_ms=0 means block indefinitely.
        timeout = None if block_ms == 0 else block_ms / 1000.0
        async with self._cond:
            try:
                while True:
                    mid, msg = _pick()
                    if mid is not None:
                        return mid, msg
                    if timeout is None:
                        await self._cond.wait()
                    else:
                        await asyncio.wait_for(self._cond.wait(), timeout)
            except asyncio.TimeoutError:
                return None, None

    async def pop(self) -> Tuple[Optional[str], Optional[Any]]:
        async with self._cond:
            if not self._items:
                return None, None
            return self._items.pop(0)

    async def get_range(
        self, start_id: str = "-", end_id: str = "+", count: int = 100
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        for mid, msg in self._items[:count]:
            if start_id != "-" and mid < start_id:
                continue
            if end_id != "+" and mid > end_id:
                break
            yield mid, msg

    async def get_latest_id(self) -> str:
        return self._items[-1][0] if self._items else "0"

    async def clear(self) -> None:
        async with self._cond:
            self._items.clear()

    async def is_empty(self) -> bool:
        return not self._items

    async def size(self) -> int:
        return len(self._items)

    async def delete_message(self, message_id: str) -> bool:
        async with self._cond:
            for i, (mid, _) in enumerate(self._items):
                if mid == message_id:
                    self._items.pop(i)
                    return True
        return False
