"""Telegram message formatters and inline keyboard builders."""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core.approvals import Approval
from ..security import redact

MAX_TELEGRAM = 3500
MAX_TERMINAL = 3500
NO_ACTIVE_FLOW_TEXT = "No tengo un flow activo seleccionado. Puedo mostrarte los flows disponibles."
SAFE_ERROR_TEXT = "Ocurrió un error seguro. No se ejecutó ninguna acción en PentAGI."


def truncate(text: str, limit: int = MAX_TELEGRAM, suffix: str = "\n\n... (truncated)") -> str:
    clean = redact(text)
    return clean if len(clean) <= limit else clean[: limit - len(suffix)] + suffix


def provider_label(provider: dict[str, Any]) -> str:
    name = provider.get("name") or provider.get("provider") or "provider"
    model = provider.get("model") or "model?"
    status = provider.get("status") or "status?"
    return f"{name} — {model} ({status})"


def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Flows", callback_data="ui:list_flows"), InlineKeyboardButton("Providers", callback_data="ui:providers")],
            [InlineKeyboardButton("Estado", callback_data="ui:active_status"), InlineKeyboardButton("Ayuda", callback_data="ui:help")],
        ]
    )


def no_active_flow_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Mostrar flows", callback_data="ui:list_flows"), InlineKeyboardButton("Ayuda", callback_data="ui:help")]]
    )


def error_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Menú", callback_data="ui:help"), InlineKeyboardButton("Flows", callback_data="ui:list_flows")]])


def stop_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Detener operación local", callback_data="ui:stop_local")]])


def flow_actions_markup(flow_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Estado", callback_data=f"flow:status:{flow_id}"), InlineKeyboardButton("Resumen", callback_data=f"flow:summary:{flow_id}")],
            [InlineKeyboardButton("Tareas", callback_data=f"flow:tasks:{flow_id}"), InlineKeyboardButton("Logs", callback_data=f"flow:logs:{flow_id}")],
            [InlineKeyboardButton("Terminal", callback_data=f"flow:terminal:{flow_id}"), InlineKeyboardButton("Watch", callback_data=f"flow:watch:{flow_id}")],
        ]
    )


def flows_markup(flows: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for flow in flows[:8]:
        flow_id = str(flow.get("id") or "")
        if flow_id.isdigit():
            label = str(flow.get("title") or flow.get("name") or flow_id)[:32]
            rows.append([InlineKeyboardButton(f"Abrir {label}", callback_data=f"flow:bind:{flow_id}")])
    rows.append([InlineKeyboardButton("Menú", callback_data="ui:help")])
    return InlineKeyboardMarkup(rows)


def approval_markup(approval: Approval) -> InlineKeyboardMarkup:
    confirm = "approval:confirm_delete" if approval.confirm_delete else "approval:confirm"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Confirmar", callback_data=f"{confirm}:{approval.code}"), InlineKeyboardButton("Denegar", callback_data=f"approval:deny:{approval.code}")],
            [InlineKeyboardButton("Detalle", callback_data=f"approval:detail:{approval.code}")],
        ]
    )


def format_flow_list(flows: list[dict[str, Any]]) -> str:
    if not flows:
        return "No hay flows disponibles."
    lines = ["*PentAGI Flows:*"]
    for flow in flows:
        flow_id = str(flow.get("id", "?"))
        lines.append(
            f"• `{flow_id}` — *{flow.get('title') or flow.get('name', '?')}*\n"
            f"   Estado: {flow.get('status', '?')} | Provider: {flow.get('provider', '?')}\n"
            f"   Actualizado: {flow.get('updatedAt', '?')}"
        )
    return truncate("\n".join(lines))


def format_flow_detail(flow: dict[str, Any] | None) -> str:
    if not flow:
        return "Flow no encontrado."
    return truncate(
        f"*Flow:* {flow.get('title') or flow.get('name', '?')}\n"
        f"ID: `{flow.get('id', '?')}`\n"
        f"Estado: {flow.get('status', '?')}\n"
        f"Provider: {flow.get('provider', '?')}\n"
        f"Creado: {flow.get('createdAt', '?')}\n"
        f"Actualizado: {flow.get('updatedAt', '?')}"
    )


def format_providers(providers: list[dict[str, Any]]) -> str:
    if not providers:
        return "No hay providers configurados."
    return truncate("\n".join(["*LLM Providers:*"] + [f"• {provider_label(p)}" for p in providers]))


def format_tasks(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "No hay tareas."
    lines = ["*Tasks:*"]
    for task in tasks:
        result = redact(str(task.get("result") or task.get("content") or task.get("text") or ""))
        summary = (result[:120] + "...") if len(result) > 120 else result
        lines.append(
            f"• `{str(task.get('id', '?'))}` — {task.get('title') or task.get('name', '?')} "
            f"[{task.get('status', '?')}]\n  {summary or '-'}"
        )
    return truncate("\n".join(lines))


def format_logs(entries: list[dict[str, Any]], log_type: str = "message", limit: int = MAX_TELEGRAM) -> str:
    if not entries:
        return f"No hay logs de tipo {log_type}."
    lines = [f"*{log_type.title()} Logs:*"]
    for entry in entries[-10:]:
        ts = (entry.get("createdAt") or "")[11:19] or ""
        role = entry.get("role", "")
        content = redact(str(entry.get("message") or entry.get("content") or entry.get("text") or entry.get("result") or ""))
        if log_type == "terminal":
            content = content[:250]
        lines.append(f"`{ts}` {role} {content}" if role else f"`{ts}` {content}")
    return truncate("\n".join(lines), limit)


def format_terminal_logs(entries: list[dict[str, Any]]) -> str:
    return format_logs(entries, "terminal", MAX_TERMINAL)


def format_summary(flow: dict[str, Any] | None, tasks: list[dict[str, Any]], logs: list[dict[str, Any]]) -> str:
    title = flow.get("title") or flow.get("name") if flow else "flow"
    status = flow.get("status") if flow else "unknown"
    recent = " | ".join(redact(str(x.get("message") or x.get("content") or x.get("text") or x.get("result") or ""))[:90] for x in (logs[-3:] or tasks[-3:]))
    return truncate(f"Resumen de {title}: estado={status}; tareas={len(tasks)}; reciente: {recent or 'sin actividad reciente'}")


def format_findings(tasks: list[dict[str, Any]], logs: list[dict[str, Any]]) -> str:
    snippets: list[str] = []
    for item in [*tasks, *logs]:
        text = redact(str(item.get("result") or item.get("message") or item.get("content") or item.get("text") or ""))
        if text:
            snippets.append(text[:160])
    return truncate("Hallazgos recientes:\n" + "\n".join(f"• {s}" for s in snippets[-8:]) if snippets else "No encontré hallazgos recientes.")


def format_approval(approval: Approval) -> str:
    return truncate(
        "⚠️ Aprobación requerida\n"
        f"Acción: `{approval.action}`\nRiesgo: {approval.risk}\n"
        f"Código: `{approval.code}`\n"
        "Usa los botones para confirmar o denegar. Los comandos son fallback."
    )


def format_mutation_result(action: str, result: dict[str, Any]) -> str:
    return truncate(f"✅ Mutación ejecutada: {action}\n{result}")


def format_events(events: list[Any]) -> str:
    if not events:
        return "Sin eventos pendientes."
    return truncate("\n".join(f"• {getattr(e, 'name', '?')} flow={getattr(e, 'flow_id', '?')}" for e in events))
