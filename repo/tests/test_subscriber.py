from __future__ import annotations

import pytest

from gateway.pentagi.subscriber import PentagiSubscriber, SubscriptionEvent, to_ws_url


def test_ws_url_conversion():
    assert to_ws_url("https://localhost:8443/api/v1/graphql").startswith("wss://")
    assert to_ws_url("http://x/graphql").startswith("ws://")


@pytest.mark.asyncio
async def test_subscriptions_disabled_dont_start():
    sub = PentagiSubscriber("https://localhost:8443/api/v1/graphql", "tok", enabled=False)
    assert await sub.connect() is False
    await sub.subscribe_flow("flow_1")
    assert sub.drain_batch() == []


def test_subscriber_dedupe_batching():
    sub = PentagiSubscriber("http://x/graphql", "tok", enabled=False)
    event = SubscriptionEvent("flowUpdated", "flow_1", {"id": 1})
    assert sub.add_event(event) is True
    assert sub.add_event(event) is False
    assert len(sub.drain_batch()) == 1
