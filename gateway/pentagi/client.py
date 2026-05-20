"""Async HTTP client for PentAGI GraphQL API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..security import redact

logger = logging.getLogger(__name__)


class PentagiClientError(Exception):
    """Base exception for PentAGI client errors."""


class PentagiClient:
    """Thin async wrapper around the PentAGI GraphQL endpoint."""

    # ── Read-only queries ────────────────────────────────────────

    PROVIDERS = """
    query Providers { providers { id name provider model baseUrl status } }
    """
    SETTINGS_PROVIDERS = """
    query SettingsProviders { settingsProviders { id name provider model baseUrl status } }
    """
    FLOWS = """
    query Flows { flows { id name description status createdAt updatedAt } }
    """
    FLOW = """
    query Flow($flowId: ID!) { flow(flowId: $flowId) { id name description status createdAt updatedAt } }
    """
    TASKS = """
    query Tasks($flowId: ID!) { tasks(flowId: $flowId) { id name status result createdAt updatedAt } }
    """
    MESSAGE_LOGS = """
    query MessageLogs($flowId: ID!, $limit: Int) { messageLogs(flowId: $flowId, limit: $limit) { id role content createdAt } }
    """
    TERMINAL_LOGS = """
    query TerminalLogs($flowId: ID!, $limit: Int) { terminalLogs(flowId: $flowId, limit: $limit) { id content createdAt } }
    """
    AGENT_LOGS = """
    query AgentLogs($flowId: ID!, $limit: Int) { agentLogs(flowId: $flowId, limit: $limit) { id agent content createdAt } }
    """

    def __init__(
        self,
        graphql_url: str,
        api_token: str,
        verify_tls: bool = False,
        timeout_connect: float = 10.0,
        timeout_read: float = 60.0,
    ) -> None:
        self._url = graphql_url
        self._token = api_token
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        limits = httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30)
        timeout = httpx.Timeout(timeout_read, connect=timeout_connect)
        self._client = httpx.AsyncClient(headers=headers, verify=verify_tls, timeout=timeout, limits=limits)

    async def close(self) -> None:
        await self._client.aclose()

    # ── Generic query runner ─────────────────────────────────────

    async def _query(self, query_str: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query_str}
        if variables:
            payload["variables"] = variables
        try:
            resp = await self._client.post(self._url, json=payload)
        except httpx.TimeoutException:
            raise PentagiClientError("GraphQL request timed out")
        except httpx.RequestError as exc:
            raise PentagiClientError(f"HTTP request failed: {exc}") from exc
        if resp.status_code == 401:
            raise PentagiClientError("API token rejected (401)")
        if resp.status_code == 422:
            raise PentagiClientError(f"GraphQL validation error: {resp.text[:300]}")
        if resp.status_code != 200:
            raise PentagiClientError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except Exception as exc:
            raise PentagiClientError(f"Invalid JSON response: {exc}") from exc
        if "errors" in data:
            msgs = [e.get("message", "?") for e in data["errors"]]
            raise PentagiClientError(f"GraphQL errors: {msgs}")
        return data.get("data", {})

    # ── Health ───────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Quick connectivity test via a lightweight introspection query."""
        try:
            await self._query("{ __typename }")
            return True
        except PentagiClientError:
            return False

    # ── Providers ────────────────────────────────────────────────

    async def list_providers(self) -> list[dict[str, Any]]:
        data = await self._query(self.PROVIDERS)
        return data.get("providers", [])

    async def get_settings_providers(self) -> list[dict[str, Any]]:
        data = await self._query(self.SETTINGS_PROVIDERS)
        return data.get("settingsProviders", [])

    # ── Flows ────────────────────────────────────────────────────

    async def list_flows(self) -> list[dict[str, Any]]:
        data = await self._query(self.FLOWS)
        return data.get("flows", [])

    async def get_flow(self, flow_id: str) -> dict[str, Any] | None:
        data = await self._query(self.FLOW, {"flowId": flow_id})
        return data.get("flow")

    # ── Tasks ────────────────────────────────────────────────────

    async def get_tasks(self, flow_id: str) -> list[dict[str, Any]]:
        data = await self._query(self.TASKS, {"flowId": flow_id})
        return data.get("tasks", [])

    # ── Logs ─────────────────────────────────────────────────────

    async def get_message_logs(self, flow_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        vars: dict[str, Any] = {"flowId": flow_id}
        if limit is not None:
            vars["limit"] = limit
        data = await self._query(self.MESSAGE_LOGS, vars)
        return data.get("messageLogs", [])

    async def get_terminal_logs(self, flow_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        vars: dict[str, Any] = {"flowId": flow_id}
        if limit is not None:
            vars["limit"] = limit
        data = await self._query(self.TERMINAL_LOGS, vars)
        return data.get("terminalLogs", [])

    async def get_agent_logs(self, flow_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        vars: dict[str, Any] = {"flowId": flow_id}
        if limit is not None:
            vars["limit"] = limit
        data = await self._query(self.AGENT_LOGS, vars)
        return data.get("agentLogs", [])
