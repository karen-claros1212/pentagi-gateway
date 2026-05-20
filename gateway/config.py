"""Configuration via environment variables with pydantic-settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Defaults are safe: read-only, no LLM, no subscriptions."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PentAGI
    pentagi_base_url: str = "https://localhost:8443"
    pentagi_graphql_path: str = "/api/v1/graphql"
    pentagi_api_token: str = ""
    pentagi_verify_tls: bool = False
    pentagi_default_provider: str = "qwen"

    # Telegram
    telegram_bot_token: str = ""
    telegram_allowed_users: str = ""
    telegram_allowed_chats: str = ""
    telegram_inline_buttons: bool = True

    # Gateway
    gateway_mode: str = "READ_ONLY"
    gateway_sqlite_path: str = "./data/gateway.sqlite"
    gateway_log_level: str = "INFO"
    approval_ttl_seconds: int = 300
    natural_language_first: bool = True
    commands_as_fallback: bool = True

    # LLM / subscriptions / dangerous actions
    llm_enabled: bool = False
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen"
    delete_flow_enabled: bool = False
    pentagi_subscriptions_enabled: bool = False

    @property
    def graphql_url(self) -> str:
        return f"{self.pentagi_base_url.rstrip('/')}{self.pentagi_graphql_path}"

    @property
    def websocket_url(self) -> str:
        url = self.graphql_url
        if url.startswith("https://"):
            return "wss://" + url.removeprefix("https://")
        if url.startswith("http://"):
            return "ws://" + url.removeprefix("http://")
        return url

    @property
    def allowed_user_ids(self) -> list[int]:
        return _parse_ints(self.telegram_allowed_users)

    @property
    def allowed_chat_ids(self) -> list[int]:
        return _parse_ints(self.telegram_allowed_chats)

    def validate(self) -> None:
        errors: list[str] = []
        if not self.pentagi_api_token:
            errors.append("PENTAGI_API_TOKEN is required")
        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required")
        valid_modes = {"READ_ONLY", "REPORT_ONLY", "ASSISTED_EXECUTION", "LOCKED"}
        if self.gateway_mode.upper() not in valid_modes:
            errors.append(f"Invalid GATEWAY_MODE: {self.gateway_mode}")
        if self.approval_ttl_seconds < 1:
            errors.append("APPROVAL_TTL_SECONDS must be positive")
        if errors:
            raise ValueError("; ".join(errors))

    def safe_dict(self) -> dict[str, object]:
        """Safe settings snapshot for logs/debugging without secrets."""
        data = self.model_dump()
        for key in ("pentagi_api_token", "telegram_bot_token", "llm_api_key"):
            if key in data:
                data[key] = "***" if data[key] else ""
        return data

    def __repr__(self) -> str:
        return f"Settings({self.safe_dict()!r})"


def _parse_ints(raw: str) -> list[int]:
    if not raw:
        return []
    parts = raw.replace(",", " ").split()
    return [int(part) for part in parts if part.strip().lstrip("-").isdigit()]
