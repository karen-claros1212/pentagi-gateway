"""Async HTTP client for PentAGI GraphQL API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .mutations import (
    CREATE_FLOW_MUTATION,
    DELETE_FLOW_MUTATION,
    FINISH_FLOW_MUTATION,
    PUT_USER_INPUT_MUTATION,
    RENAME_FLOW_MUTATION,
    STOP_FLOW_MUTATION,
)
from .queries import (
    AGENT_LOGS_QUERY,
    FLOW_QUERY,
    FLOWS_QUERY,
    MESSAGE_LOGS_QUERY,
    PROVIDERS_QUERY,
    SETTINGS_PROVIDERS_QUERY,
    TASKS_QUERY,
    TERMINAL_LOGS_QUERY,
)

logger = logging.getLogger(__name__)


class PentagiClientError(Exception):
    """Base exception for PentAGI client errors."""


class PentagiClient:
    """Thin async wrapper around the PentAGI GraphQL endpoint."""

    PROVIDERS = PROVIDERS_QUERY
    SETTINGS_PROVIDERS = SETTINGS_PROVIDERS_QUERY
    FLOWS = FLOWS_QUERY
    FLOW = FLOW_QUERY
    TASKS = TASKS_QUERY
    MESSAGE_LOGS = MESSAGE_LOGS_QUERY
    TERMINAL_LOGS = TERMINAL_LOGS_QUERY
    AGENT_LOGS = AGENT_LOGS_QUERY

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
        headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
        limits = httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30)
        timeout = httpx.Timeout(timeout_read, connect=timeout_connect)
        self._client = httpx.AsyncClient(headers=headers, verify=verify_tls, timeout=timeout, limits=limits)

    async def close(self) -> None:
        await self._client.aclose()

    async def graphql_request(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        try:
            resp = await self._client.post(self._url, json=payload)
        except httpx.TimeoutException as exc:
            raise PentagiClientError("GraphQL request timed out") from exc
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
        except Exception as exc:  # noqa: BLE001 - convert to client error
            raise PentagiClientError(f"Invalid JSON response: {exc}") from exc
        if "errors" in data:
            msgs = [e.get("message", "?") for e in data["errors"]]
            raise PentagiClientError(f"GraphQL errors: {msgs}")
        return data.get("data", {})

    async def _query(self, query_str: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.graphql_request(query_str, variables)

    async def health_check(self) -> bool:
        try:
            await self._query("{ __typename }")
            return True
        except PentagiClientError:
            return False

    async def list_providers(self) -> list[dict[str, Any]]:
        data = await self._query(PROVIDERS_QUERY)
        return data.get("providers", [])

    async def get_settings_providers(self) -> list[dict[str, Any]]:
        data = await self._query(SETTINGS_PROVIDERS_QUERY)
        return data.get("settingsProviders", [])

    async def list_flows(self) -> list[dict[str, Any]]:
        data = await self._query(FLOWS_QUERY)
        return data.get("flows", [])

    async def get_flow(self, flow_id: str) -> dict[str, Any] | None:
        data = await self._query(FLOW_QUERY, {"flowId": flow_id})
        return data.get("flow")

    async def get_tasks(self, flow_id: str) -> list[dict[str, Any]]:
        data = await self._query(TASKS_QUERY, {"flowId": flow_id})
        return data.get("tasks", [])

    async def get_message_logs(self, flow_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        variables: dict[str, Any] = {"flowId": flow_id}
        if limit is not None:
            variables["limit"] = limit
        data = await self._query(MESSAGE_LOGS_QUERY, variables)
        return data.get("messageLogs", [])

    async def get_terminal_logs(self, flow_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        variables: dict[str, Any] = {"flowId": flow_id}
        if limit is not None:
            variables["limit"] = limit
        data = await self._query(TERMINAL_LOGS_QUERY, variables)
        return data.get("terminalLogs", [])

    async def get_agent_logs(self, flow_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        variables: dict[str, Any] = {"flowId": flow_id}
        if limit is not None:
            variables["limit"] = limit
        data = await self._query(AGENT_LOGS_QUERY, variables)
        return data.get("agentLogs", [])

    async def create_flow(self, input_data: dict[str, Any]) -> dict[str, Any]:
        data = await self.graphql_request(CREATE_FLOW_MUTATION, {"input": input_data})
        return data.get("createFlow", {})

    async def put_user_input(self, flow_id: str, user_input: str) -> dict[str, Any]:
        data = await self.graphql_request(PUT_USER_INPUT_MUTATION, {"flowId": flow_id, "input": user_input})
        return data.get("putUserInput", {})

    async def stop_flow(self, flow_id: str) -> dict[str, Any]:
        data = await self.graphql_request(STOP_FLOW_MUTATION, {"flowId": flow_id})
        return data.get("stopFlow", {})

    async def finish_flow(self, flow_id: str) -> dict[str, Any]:
        data = await self.graphql_request(FINISH_FLOW_MUTATION, {"flowId": flow_id})
        return data.get("finishFlow", {})

    async def rename_flow(self, flow_id: str, name: str) -> dict[str, Any]:
        data = await self.graphql_request(RENAME_FLOW_MUTATION, {"flowId": flow_id, "name": name})
        return data.get("renameFlow", {})

    async def delete_flow(self, flow_id: str) -> dict[str, Any]:
        data = await self.graphql_request(DELETE_FLOW_MUTATION, {"flowId": flow_id})
        return {"deleteFlow": data.get("deleteFlow")}
