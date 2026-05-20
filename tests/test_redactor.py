"""Test security redactor."""

from gateway.security import redact, redact_dict
from gateway.telegram.formatter import format_terminal_logs


def test_redact_bearer():
    assert redact("Bearer eyJhbGci.eyJzdWI.abc123") == "***"


def test_redact_sk_key():
    assert redact("sk-proj-ABC123def456789012345") == "***"


def test_redact_github():
    assert redact("ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA") == "***"


def test_redact_jwt():
    assert redact("eyJhbGciOiJIUzI1NiJ9.eyJ0ZXN0Ijp0cnVlfQ.deadbeef") == "***"


def test_redact_telegram_token():
    assert redact("8347753726:AAHkN-XrNnkybIwZcnWSaBXdgX2LHSUe-1A") == "***"


def test_redact_env_assignment():
    assert redact("TELEGRAM_BOT_TOKEN=secret") == "***"


def test_redact_dict_sensitive_keys():
    data = {"api_key": "secret123", "name": "bob"}
    redacted = redact_dict(data)
    assert redacted["api_key"] == "***"
    assert redacted["name"] == "bob"


def test_redact_dict_bearer_value():
    data = {"auth": "Bearer tok123", "x": "y"}
    redacted = redact_dict(data)
    assert redacted["auth"] == "***"


def test_terminal_formatter_redacts_secrets():
    text = format_terminal_logs([{"content": "PENTAGI_API_TOKEN=abc", "createdAt": "now"}])
    assert "abc" not in text
    assert "***" in text
