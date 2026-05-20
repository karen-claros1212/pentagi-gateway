"""Test PentagiClient with mocked HTTP."""

import httpx
import pytest
from gateway.pentagi.client import PentagiClient, PentagiClientError


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, status=200, payload=None):
        self._status = status
        self._payload = payload or {"data": {}}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        return httpx.Response(self._status, json=self._payload)


@pytest.mark.asyncio
async def test_health_ok():
    t = MockTransport(200, {"data": {"__typename": "Query"}})
    async with httpx.AsyncClient(transport=t) as c:
        client = PentagiClient("http://x/graphql", "tok")
        client._client = c
        assert await client.health_check() is True


@pytest.mark.asyncio
async def test_health_fail():
    t = MockTransport(401, {"error": "unauthorized"})
    async with httpx.AsyncClient(transport=t) as c:
        client = PentagiClient("http://x/graphql", "bad")
        client._client = c
        assert await client.health_check() is False


@pytest.mark.asyncio
async def test_list_providers():
    t = MockTransport(200, {"data": {"providers": [{"name": "qwen", "model": "qwen-3.5", "status": "connected"}]}})
    async with httpx.AsyncClient(transport=t) as c:
        client = PentagiClient("http://x/graphql", "tok")
        client._client = c
        providers = await client.list_providers()
        assert len(providers) == 1
        assert providers[0]["name"] == "qwen"


@pytest.mark.asyncio
async def test_graphql_error():
    t = MockTransport(200, {"errors": [{"message": "field not found"}]})
    async with httpx.AsyncClient(transport=t) as c:
        client = PentagiClient("http://x/graphql", "tok")
        client._client = c
        with pytest.raises(PentagiClientError, match="field not found"):
            await client.list_providers()


@pytest.mark.asyncio
async def test_timeout():
    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await request.aread()
            raise httpx.TimeoutException("timed out")

    async with httpx.AsyncClient(transport=SlowTransport()) as c:
        client = PentagiClient("http://x/graphql", "tok")
        client._client = c
        with pytest.raises(PentagiClientError, match="timed out"):
            await client.list_providers()
