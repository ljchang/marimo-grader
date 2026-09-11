"""In-process event bus feeding the per-offering Server-Sent Events stream.

Single-process v1. When grader-web runs with several replicas this becomes a
PostgreSQL LISTEN/NOTIFY relay; the publish/subscribe interface stays the same.
The worker publishes through the ``events_outbox`` pattern below: it inserts a
row, and the API's poller turns rows into events.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Event:
    offering_id: uuid.UUID
    type: str
    data: dict = field(default_factory=dict)

    def sse(self) -> dict:
        return {"event": self.type, "data": json.dumps(self.data, default=str)}


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, set[asyncio.Queue[Event]]] = defaultdict(set)

    def publish(self, ev: Event) -> None:
        for q in list(self._subs.get(ev.offering_id, ())):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:  # slow consumer: drop, client will refetch
                pass

    def subscribe(self, offering_id: uuid.UUID) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=256)
        self._subs[offering_id].add(q)
        return q

    def unsubscribe(self, offering_id: uuid.UUID, q: asyncio.Queue[Event]) -> None:
        self._subs[offering_id].discard(q)


bus = EventBus()
