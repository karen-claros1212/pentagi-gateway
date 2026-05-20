"""Configuration via environment variables with pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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

    # Gateway
    gateway_mode: str = "READ_ONLY"
    gateway_sqlite_path: str = "./data/gateway.sqlite"
    gateway_log_level: str = "INFO"

    @property
    def graphql_url(self) -> str:
        return f"{self.pentagi_base_url.rstrip('/')}{self.pentagi_graphql_path}"

    @property
    def allowed_user_ids(self) -> list[int]:
        if not self.telegram_allowed_users:
            return []
        parts = self.telegram_allowed_users.replace(",", " ").split()
        return [int(p) for p in parts if p.strip().isdigit()]

    @property
    def allowed_chat_ids(self) -> list[int]:
        if not self.telegram_allowed_chats:
            return []
        parts = self.telegram_allowed_chats.replace(",", " ").split()
        return [int(p) for p in parts if p.strip().isdigit()]

    def validate(self) -> None:
        errors: list[str] = []
        if not self.pentagi_api_token:
            errors.append("PENTAGI_API_TOKEN is required")
        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required")
        if self.gateway_mode.upper() not in ("READ_ONLY", "OPERATOR", "ADMIN"):
            errors.append(f"Invalid GATEWAY_MODE: {self.gateway_mode}")
        if errors:
            raise ValueError("; ".join(errors))
