"""Test security redactor."""

from gateway.security import redact, redact_dict


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


def test_redact_dict_sensitive_keys():
    d = {"api_key": "secret123", "name": "bob"}
    r = redact_dict(d)
    assert r["api_key"] == "***"
    assert r["name"] == "bob"


def test_redact_dict_bearer_value():
    d = {"auth": "Bearer tok123", "x": "y"}
    r = redact_dict(d)
    assert r["auth"] == "***"
