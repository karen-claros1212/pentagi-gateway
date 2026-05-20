"""Telegram message formatters — PentAGI v2.0.0 schema compatible."""

from __future__ import annotations

from typing import Any

from ..core.approvals import Approval
from ..security import redact

MAX_TELEGRAM = 3500
MAX_TERMINAL = 3500


def truncate(text: str, limit: int = MAX_TELEGRAM, suffix: str = "\n\n... (truncated)") -> str:
    clean = redact(text)
    return clean if len(clean) <= limit else clean[: limit - len(suffix)] + suffix


def _provider_label(p: Any) -> str:
    """Format provider dict {name, type} or fallback to string."""
    if isinstance(p, dict):
        return f"{p.get('name', '?')} ({p.get('type', '?')})"
    return str(p or "?")


def format_flow_list(flows: list[dict[str, Any]]) -> str:
    if not flows:
        return "No flows found."
    lines = ["*PentAGI Flows:*"]
    for flow in flows:
        lines.append(
            f"• `{str(flow.get('id', '?'))[:12]}` — *{flow.get('title', '?')}*\n"
            f"   Status: {flow.get('status', '?')} | Provider: {_provider_label(flow.get('provider'))}\n"
            f"   Updated: {flow.get('updatedAt', '?')}"
        )
    return truncate("\n".join(lines))


def format_flow_detail(flow: dict[str, Any] | None) -> str:
    if not flow:
        return "Flow not found."
    return truncate(
        f"*Flow:* {flow.get('title', '?')}\n"
        f"ID: `{flow.get('id', '?')}`\n"
        f"Status: {flow.get('status', '?')}\n"
        f"Provider: {_provider_label(flow.get('provider'))}\n"
        f"Created: {flow.get('createdAt', '?')}\n"
        f"Updated: {flow.get('updatedAt', '?')}"
    )


def format_providers(providers: list[dict[str, Any]]) -> str:
    if not providers:
        return "No providers configured."
    lines = ["*LLM Providers:*"]
    for p in providers:
        lines.append(f"• {p.get('name', '?')} — {p.get('type', '?')}")
    return truncate("\n".join(lines))


def format_tasks(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "No tasks."
    lines = ["*Tasks:*"]
    for task in tasks:
        result = redact(str(task.get("result") or ""))
        summary = (result[:120] + "...") if len(result) > 120 else result
        lines.append(
            f"• `{str(task.get('id', '?'))[:12]}` — {task.get('title', '?')} [{task.get('status', '?')}]\n"
            f"  {summary or '-'}"
        )
    return truncate("\n".join(lines))


def format_logs(entries: list[dict[str, Any]], log_type: str = "message", limit: int = MAX_TELEGRAM) -> str:
    if not entries:
        return f"No {log_type} logs."
    lines = [f"*{log_type.title()} Logs:*"]
    for entry in entries[-10:]:
        ts = (entry.get("createdAt") or "")[11:19] or ""
        if log_type == "message":
            role = entry.get("type", "")
            content = redact(str(entry.get("message") or ""))
            think = entry.get("thinking", "")
            if think:
                content = f"{content} 🧠 {redact(str(think)[:200])}"
        elif log_type == "terminal":
            role = entry.get("type", "")
            content = redact(str(entry.get("text") or ""))[:250]
        else:
            role = entry.get("type", "")
            content = redact(str(entry.get("text") or entry.get("message") or ""))
        lines.append(f"`{ts}` {role} {content}" if role else f"`{ts}` {content}")
    return truncate("\n".join(lines), limit)


def format_terminal_logs(entries: list[dict[str, Any]]) -> str:
    return format_logs(entries, "terminal", MAX_TERMINAL)


def format_summary(flow: dict[str, Any] | None, tasks: list[dict[str, Any]], logs: list[dict[str, Any]]) -> str:
    title = flow.get("title", "flow") if flow else "flow"
    status = flow.get("status") if flow else "unknown"
    recent_items = [(x.get("message") or x.get("text") or x.get("result") or "") for x in (logs[-3:] or tasks[-3:])]
    recent = " | ".join(redact(str(c))[:90] for c in recent_items)
    return truncate(f"Resumen de {title}: estado={status}; tareas={len(tasks)}; reciente: {recent or 'sin actividad reciente'}")


def format_findings(tasks: list[dict[str, Any]], logs: list[dict[str, Any]]) -> str:
    snippets: list[str] = []
    for item in [*tasks, *logs]:
        text = redact(str(item.get("result") or item.get("message") or item.get("text") or ""))
        if text:
            snippets.append(text[:160])
    return truncate("Hallazgos recientes:\n" + "\n".join(f"• {s}" for s in snippets[-8:]) if snippets else "No encontré hallazgos recientes.")


def format_approval(approval: Approval) -> str:
    cmd = "/confirm_delete" if approval.confirm_delete else "/confirm"
    return truncate(
        f"⚠️ Aprobación requerida\n"
        f"Acción: `{approval.action}`\nRiesgo: {approval.risk}\n"
        f"Código: `{approval.code}`\n"
        f"Ejecuta `{cmd} {approval.code}` para confirmar o `/deny {approval.code}` para cancelar."
    )


def format_mutation_result(action: str, result: dict[str, Any]) -> str:
    return truncate(f"✅ Mutación ejecutada: {action}\n{result}")


def format_events(events: list[Any]) -> str:
    if not events:
        return "Sin eventos pendientes."
    return truncate("\n".join(f"• {getattr(e, 'name', '?')} flow={getattr(e, 'flow_id', '?')}" for e in events))
