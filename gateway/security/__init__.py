"""Redact sensitive data before logging / output."""

from __future__ import annotations

import re
from typing import Any

# Patterns for known secret formats
SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Bearer\s+[\w\-._~+/]+=*", re.I),
    re.compile(r"sk-[a-zA-Z0-9-_]{20,}", re.I),
    re.compile(r"ghp_\w{36,}", re.I),
    re.compile(r"xox[baprs]-\d+-\d+-\w+", re.I),
    re.compile(r"AKIA[0-9A-Z]{16}", re.I),
    re.compile(r"[Aa]uthorization:\s*\S+", re.I),
    re.compile(r"Set-Cookie:\s*\S+", re.I),
    re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[\w\-_+/]+=*"),
    re.compile(r"\d{8,10}:[a-zA-Z0-9_-]{35,}"),
]


def redact(text: str, replacement: str = "***") -> str:
    """Replace all known secret patterns with ***."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_dict(data: dict[str, Any], keys: set[str] | None = None) -> dict[str, Any]:
    """Return a copy of dict with sensitive values redacted."""
    sensitive_keys = keys or {"token", "api_key", "password", "secret", "cookie", "authorization"}
    result = dict(data)
    for k, v in result.items():
        if any(s in k.lower() for s in sensitive_keys) and isinstance(v, str):
            result[k] = "***"
        elif isinstance(v, str):
            result[k] = redact(v)
    return result
