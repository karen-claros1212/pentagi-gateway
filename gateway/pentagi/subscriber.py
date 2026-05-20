"""PentAGI websocket subscription skeleton, disabled by default."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import websockets

logger = logging.getLogger(__name__)

SUBSCRIPTION_NAMES = (
    "flowUpdated",
    "taskCreated",
    "taskUpdated",
    "messageLogAdded",
    "messageLogUpdated",
    "terminalLogAdded",
    "agentLogAdded",
    "assistantLogAdded",
    "assistantLogUpdated",
    "screenshotAdded",
)


@dataclass
class SubscriptionEvent:
    name: str
    flow_id: str
    payload: dict[str, Any]
    received_at: float = field(default_factory=time.time)


class PentagiSubscriber:
    """Safe skeleton for future subscriptions; no connection when disabled."""

    def __init__(self, graphql_url: str, api_token: str, enabled: bool = False) -> None:
        self.ws_url = to_ws_url(graphql_url)
        self.api_token = api_token
        self.enabled = enabled
        self._ws: Any = None
        self._running = False
        self._seen: set[str] = set()
        self._events: deque[SubscriptionEvent] = deque(maxlen=200)
        self._subscriptions: set[str] = set()

    async def connect(self) -> bool:
        if not self.enabled:
            logger.info("PentAGI subscriptions disabled")
            return False
        self._running = True
        self._ws = await websockets.connect(self.ws_url, additional_headers=self._headers())
        return True

    async def subscribe_flow(self, flow_id: str) -> None:
        if not self.enabled:
            return
        self._subscriptions.add(flow_id)
        await self._send({"type": "subscribe", "flowId": flow_id, "names": list(SUBSCRIPTION_NAMES)})

    async def unsubscribe_flow(self, flow_id: str) -> None:
        self._subscriptions.discard(flow_id)
        if self.enabled:
            await self._send({"type": "unsubscribe", "flowId": flow_id})

    async def reconnect_backoff(self, attempts: int = 5) -> bool:
        for attempt in range(attempts):
            await asyncio.sleep(min(2**attempt, 30))
            try:
                return await self.connect()
            except Exception as exc:  # noqa: BLE001 - skeleton must keep retrying
                logger.warning("subscription reconnect failed: %s", exc)
        return False

    async def shutdown(self) -> None:
        self._running = False
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    def add_event(self, event: SubscriptionEvent) -> bool:
        key = f"{event.name}:{event.flow_id}:{json.dumps(event.payload, sort_keys=True)}"
        if key in self._seen:
            return False
        self._seen.add(key)
        self._events.append(event)
        return True

    def drain_batch(self, max_items: int = 20) -> list[SubscriptionEvent]:
        items: list[SubscriptionEvent] = []
        while self._events and len(items) < max_items:
            items.append(self._events.popleft())
        return items

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps(payload))


def to_ws_url(graphql_url: str) -> str:
    if graphql_url.startswith("https://"):
        return "wss://" + graphql_url.removeprefix("https://")
    if graphql_url.startswith("http://"):
        return "ws://" + graphql_url.removeprefix("http://")
    return graphql_url
