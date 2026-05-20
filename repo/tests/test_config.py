"""Test configuration."""

import pytest

from gateway.config import Settings


def test_defaults():
    s = Settings()
    assert s.pentagi_base_url == "https://localhost:8443"
    assert s.gateway_mode == "READ_ONLY"
    assert s.llm_enabled is False
    assert s.delete_flow_enabled is False
    assert s.pentagi_subscriptions_enabled is False
    assert s.approval_ttl_seconds == 300
    assert s.natural_language_first is True
    assert s.commands_as_fallback is True
    assert s.telegram_inline_buttons is True


def test_graphql_url():
    s = Settings()
    assert "/api/v1/graphql" in s.graphql_url
    assert s.websocket_url.startswith("wss://")


def test_allowed_users():
    s = Settings(telegram_allowed_users="123 456")
    assert s.allowed_user_ids == [123, 456]


def test_allowed_users_csv():
    s = Settings(telegram_allowed_users="123,456,789")
    assert 123 in s.allowed_user_ids
    assert 789 in s.allowed_user_ids


def test_validate_missing_token():
    s = Settings()
    with pytest.raises(ValueError, match="PENTAGI_API_TOKEN"):
        s.validate()


def test_validate_ok():
    s = Settings(pentagi_api_token="tok", telegram_bot_token="bot")
    s.validate()


def test_invalid_mode():
    with pytest.raises(ValueError, match="GATEWAY_MODE"):
        Settings(gateway_mode="INVALID").validate()


def test_safe_repr_redacts():
    s = Settings(pentagi_api_token="super-secret-api", telegram_bot_token="super-secret-bot", llm_api_key="super-secret-llm")
    assert "super-secret-api" not in repr(s)
    assert "super-secret-bot" not in repr(s)
    assert "super-secret-llm" not in repr(s)
