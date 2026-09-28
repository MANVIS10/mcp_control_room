"""In-memory SSE fan-out: every connected browser tab gets its own queue."""

from __future__ import annotations

import asyncio
from collections import deque


class Broadcaster:
    def __init__(self, buffer_size: int = 500, history_size: int = 100) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._history: deque[dict] = deque(maxlen=history_size)
        self._buffer_size = buffer_size

    def subscribe(self, last_event_id: str | None = None) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._buffer_size)
        ids = [event["id"] for event in self._history]
        if last_event_id in ids:
            for event in list(self._history)[ids.index(last_event_id) + 1 :]:
                queue.put_nowait(event)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict) -> None:
        self._history.append(event)
        for queue in list(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
