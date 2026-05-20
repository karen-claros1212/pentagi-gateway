"""Telegram message formatters."""

from __future__ import annotations

from typing import Any

from ..security import redact

MAX_TELEGRAM = 4000
MAX_TERMINAL = 3500


def _truncate(text: str, limit: int = MAX_TELEGRAM, suffix: str = "\n\n... (truncated)") -> str:
    return text if len(text) <= limit else text[: limit - len(suffix)] + suffix


def format_flow_list(flows: list[dict[str, Any]]) -> str:
    if not flows:
        return "No flows found."
    lines = ["*PentAGI Flows:*"]
    for f in flows:
        lines.append(
            f"• `{f.get('id','?')[:8]}` — *{f.get('title') or f.get('name','?')}*\n"
            f"   Status: {f.get('status','?')} | Provider: {f.get('provider','?')}\n"
            f"   Created: {f.get('createdAt','?')} | Updated: {f.get('updatedAt','?')}"
        )
    return _truncate("\n".join(lines))


def format_flow_detail(f: dict[str, Any] | None) -> str:
    if not f:
        return "Flow not found."
    return _truncate(
        f"*Flow:* {f.get('title') or f.get('name','?')}\n"
        f"ID: `{f.get('id','?')}`\n"
        f"Status: {f.get('status','?')}\n"
        f"Provider: {f.get('provider','?')}\n"
        f"Created: {f.get('createdAt','?')}\n"
        f"Updated: {f.get('updatedAt','?')}"
    )


def format_providers(providers: list[dict[str, Any]]) -> str:
    if not providers:
        return "No providers configured."
    lines = ["*LLM Providers:*"]
    for p in providers:
        lines.append(
            f"• {p.get('name') or p.get('provider','?')}\n"
            f"   Model: {p.get('model','?')} | Status: {p.get('status','?')}"
        )
    return "\n".join(lines)


def format_tasks(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "No tasks."
    lines = ["*Tasks:*"]
    for t in tasks:
        result = t.get("result") or ""
        summary = (result[:100] + "...") if len(result) > 100 else result
        lines.append(
            f"• `{t.get('id','?')[:8]}` — *{t.get('title') or t.get('name','?')}*\n"
            f"   Status: {t.get('status','?')}\n"
            f"   Result: {summary or '-'}"
        )
    return _truncate("\n".join(lines))


def format_logs(entries: list[dict[str, Any]], log_type: str = "message", limit: int = MAX_TELEGRAM) -> str:
    if not entries:
        return f"No {log_type} logs."
    lines = [f"*{log_type.title()} Logs:*"]
    for e in entries[-10:]:
        ts = (e.get("createdAt") or "")[11:19] or ""
        role = e.get("role", "")
        content = redact(str(e.get("content") or ""))
        if log_type == "terminal":
            content = content[:200]
        line = f"`{ts}` {role} {content}" if role else f"`{ts}` {content}"
        lines.append(line)
    return _truncate("\n".join(lines), limit)


def format_terminal_logs(entries: list[dict[str, Any]]) -> str:
    return format_logs(entries, "terminal", MAX_TERMINAL)


def format_provider_status(providers: list[dict[str, Any]]) -> str:
    lines = ["*Provider Status:*"]
    for p in providers:
        emoji = "🟢" if p.get("status") == "connected" else "🔴"
        lines.append(f"{emoji} {p.get('name','?')} → {p.get('model','?')}")
    return "\n".join(lines)
