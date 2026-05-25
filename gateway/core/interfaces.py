"""Abstract interfaces for all gateway services.

Following Dola App Pattern #3: ServiceManager + dependency inversion.
Enables testability via mocks without coupling to concrete implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ISessionStore(ABC):
    """Session, audit, approval and rate-limit persistence."""

    @property
    @abstractmethod
    def conn(self) -> Any:
        """SQLite connection for direct queries (used by ApprovalStore)."""
        ...

    @abstractmethod
    async def open(self) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...

    @abstractmethod
    async def get_session(self, chat_id: int, user_id: int) -> Any | None:
        ...

    @abstractmethod
    async def ensure_session(self, chat_id: int, user_id: int, role: str = "readonly") -> Any:
        ...

    @abstractmethod
    async def upsert_session(self, session: Any) -> None:
        ...

    @abstractmethod
    async def bind_flow(self, chat_id: int, user_id: int, flow_id: str) -> None:
        ...

    @abstractmethod
    async def audit(
        self,
        user_id: int,
        chat_id: int,
        action: str,
        risk: str = "low",
        allowed: bool = True,
        reason: str = "",
    ) -> int:
        ...


class IPentagiClient(ABC):
    """Async GraphQL client for PentAGI backend."""

    @abstractmethod
    async def close(self) -> None:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    @abstractmethod
    async def list_providers(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_settings_providers(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def list_flows(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_flow(self, flow_id: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def get_tasks(self, flow_id: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_message_logs(self, flow_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_terminal_logs(self, flow_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_agent_logs(self, flow_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_assistants(self, flow_id: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def create_flow(
        self,
        input_data: dict[str, Any] | str,
        model_provider: str = "qwen",
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def put_user_input(self, flow_id: str, user_input: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def stop_flow(self, flow_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def finish_flow(self, flow_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def rename_flow(self, flow_id: str, title: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def delete_flow(self, flow_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def create_assistant(
        self,
        flow_id: str,
        model_provider: str = "qwen",
        input_text: str = "",
        use_agents: bool = False,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def call_assistant(
        self,
        flow_id: str,
        assistant_id: str,
        input_text: str = "",
        use_agents: bool = False,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def stop_assistant(self, flow_id: str, assistant_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def delete_assistant(self, flow_id: str, assistant_id: str) -> dict[str, Any]:
        ...


class IAuthProvider(ABC):
    """Authentication and role resolution."""

    @abstractmethod
    def is_authorized(self, user_id: int, chat_id: int | None = None) -> bool:
        ...

    @abstractmethod
    def resolve_role(self, user_id: int) -> Any:
        ...

    @abstractmethod
    def build_context(self, user_id: int, chat_id: int, username: str | None = None) -> Any:
        ...


class IRateLimiter(ABC):
    """Rate limiter for Telegram commands."""

    @abstractmethod
    def is_allowed(self, key: str, max_requests: int | None = None) -> bool:
        ...

    @abstractmethod
    def remaining(self, key: str, max_requests: int | None = None) -> int:
        ...
