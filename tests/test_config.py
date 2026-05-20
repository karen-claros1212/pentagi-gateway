"""Test configuration."""

import pytest
from gateway.config import Settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.pentagi_base_url == "https://localhost:8443"


def test_graphql_url():
    s = Settings(_env_file=None)
    assert "/api/v1/graphql" in s.graphql_url


def test_allowed_users():
    s = Settings(telegram_allowed_users="123 456", _env_file=None)
    assert s.allowed_user_ids == [123, 456]


def test_allowed_users_csv():
    s = Settings(telegram_allowed_users="123,456,789", _env_file=None)
    assert 123 in s.allowed_user_ids
    assert 789 in s.allowed_user_ids


def test_validate_missing_token(monkeypatch):
    monkeypatch.delenv("PENTAGI_API_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot")
    s = Settings(_env_file=None)
    with pytest.raises(ValueError, match="PENTAGI_API_TOKEN"):
        s.validate()


def test_validate_ok():
    s = Settings(pentagi_api_token="tok", telegram_bot_token="bot", _env_file=None)
    s.validate()  # no error


def test_invalid_mode():
    with pytest.raises(ValueError, match="GATEWAY_MODE"):
        Settings(gateway_mode="INVALID", pentagi_api_token="tok", telegram_bot_token="bot", _env_file=None).validate()
