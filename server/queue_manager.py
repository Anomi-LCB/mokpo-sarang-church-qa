from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class _Waiter:
    ticket_id: str
    event: asyncio.Event


class QueryQueueManager:
    """Async FIFO concurrency limiter with real-time queue position updates for multi-user CLI queries."""

    def __init__(self, max_concurrent: int = 2):
        self._max_concurrent = max(1, max_concurrent)
        self._active = 0
        self._waiters: deque[_Waiter] = deque()
        self._notify_cond = asyncio.Condition()

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def status(self) -> dict[str, int]:
        return {
            "active": self._active,
            "queued": len(self._waiters),
            "max_concurrent": self._max_concurrent,
        }

    async def set_max_concurrent(self, value: int) -> None:
        async with self._notify_cond:
            self._max_concurrent = max(1, min(6, int(value)))
            self._wake_next_locked()
            self._notify_cond.notify_all()

    def _wake_next_locked(self) -> None:
        while self._active < self._max_concurrent and self._waiters:
            w = self._waiters.popleft()
            self._active += 1
            w.event.set()

    async def wait_turn(self, ticket_id: str) -> AsyncIterator[dict[str, int | str]]:
        """Yield queue status updates until a worker slot is granted. Caller must call release() in finally."""
        waiter: _Waiter | None = None
        async with self._notify_cond:
            if self._active < self._max_concurrent and not self._waiters:
                self._active += 1
                yield {
                    "stage": "acquired",
                    "position": 0,
                    "active": self._active,
                    "max_concurrent": self._max_concurrent,
                }
                return
            waiter = _Waiter(ticket_id=ticket_id, event=asyncio.Event())
            self._waiters.append(waiter)

        try:
            while not waiter.event.is_set():
                async with self._notify_cond:
                    if waiter.event.is_set():
                        break
                    pos = next((i + 1 for i, w in enumerate(self._waiters) if w.ticket_id == ticket_id), 1)
                    yield {
                        "stage": "queued",
                        "position": pos,
                        "active": self._active,
                        "max_concurrent": self._max_concurrent,
                    }
                    try:
                        await asyncio.wait_for(self._notify_cond.wait(), timeout=2.0)
                    except TimeoutError:
                        pass
            yield {
                "stage": "acquired",
                "position": 0,
                "active": self._active,
                "max_concurrent": self._max_concurrent,
            }
        except asyncio.CancelledError:
            async with self._notify_cond:
                if waiter.event.is_set():
                    self._active = max(0, self._active - 1)
                    self._wake_next_locked()
                else:
                    self._waiters = deque(w for w in self._waiters if w.ticket_id != ticket_id)
                self._notify_cond.notify_all()
            raise

    async def release(self) -> None:
        async with self._notify_cond:
            self._active = max(0, self._active - 1)
            self._wake_next_locked()
            self._notify_cond.notify_all()
