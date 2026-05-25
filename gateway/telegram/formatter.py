"""Telegram message formatters and inline keyboard builders.

Includes UI screen functions for the state machine adapter (patch 8).
"""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core.approvals import Approval
from ..core.session import TelegramSession
from ..security import redact

MAX_TELEGRAM = 3500
MAX_TERMINAL = 3500
NO_ACTIVE_FLOW_TEXT = (
    "Ahora mismo no tengo un flow activo seleccionado. "
    "Elige un flow para operar con resumen, tareas, logs, terminal y hallazgos."
)
SAFE_ERROR_TEXT = "Ocurrió un error seguro. No se ejecutó ninguna acción en PentAGI."

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def truncate(text: str, limit: int = MAX_TELEGRAM, suffix: str = "\n\n... (truncated)") -> str:
    clean = redact(text)
    return clean if len(clean) <= limit else clean[: limit - len(suffix)] + suffix


def provider_label(provider: dict[str, Any] | str | None) -> str:
    if not isinstance(provider, dict):
        return str(provider or "-")
    name = provider.get("name") or provider.get("provider") or "provider"
    provider_type = provider.get("type")
    return f"{name} ({provider_type})" if provider_type else str(name)


# ---------------------------------------------------------------------------
# UI Screen Functions  (patch 8)
# ---------------------------------------------------------------------------


def home_screen(session: TelegramSession, providers: list[dict[str, Any]], templates: list[dict[str, Any]], gateway_mode: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """Pantalla principal con navegación directa a todas las acciones de PentAGI."""
    mode_label = (gateway_mode or session.mode or "ASSISTED_EXECUTION").upper()
    parts = [f"🏠 *PentAGI Gateway* [{mode_label}]"]
    if session.active_flow_id:
        status = session.active_flow_status or "unknown"
        parts.append(f"⚙️ Flow activo: `{session.active_flow_id}` [{status}]")
    else:
        parts.append("Sin flow activo seleccionado.")
    text = "\\n".join(parts)
    kb = [
        [InlineKeyboardButton("💬 Asistente", callback_data="ui:assistant"),
         InlineKeyboardButton("▶️ Trabajar", callback_data="ui:new_flow")],
        [InlineKeyboardButton("📊 Flows", callback_data="ui:flows"),
         InlineKeyboardButton("📋 Tareas", callback_data="ui:tasks")],
        [InlineKeyboardButton("🧾 Logs", callback_data="ui:logs"),
         InlineKeyboardButton("🖥 Terminal", callback_data="ui:terminal")],
        [InlineKeyboardButton("⏹ Stop", callback_data="ui:stop_flow"),
         InlineKeyboardButton("❓ Ayuda", callback_data="ui:help")],
    ]
    return text, InlineKeyboardMarkup(kb)


def new_flow_draft_screen(session: TelegramSession, providers: list[dict[str, Any]], templates: list[dict[str, Any]]) -> tuple[str, InlineKeyboardMarkup]:
    """Formulario para crear un nuevo flow: objetivo + provider + template."""
    parts = ["✏️ *Nuevo Flow*"]
    if session.draft_message:
        parts.append(f"Objetivo: `{session.draft_message[:200]}`")
    else:
        parts.append("Escribe tu objetivo para el nuevo flow.")
    parts.append(f"Provider: {session.selected_provider or 'no seleccionado'}")
    parts.append(f"Template: {session.draft_template_id or 'ninguno'}")
    text = "\n".join(parts)
    kb = [
        [InlineKeyboardButton("Seleccionar Provider", callback_data="ui:providers")],
        [InlineKeyboardButton("Seleccionar Template", callback_data="ui:templates")],
    ]
    if session.draft_message:
        kb.append([InlineKeyboardButton("✅ Enviar Draft", callback_data="ui:submit_draft")])
    kb.append([InlineKeyboardButton("🔙 Volver", callback_data="ui:home")])
    return text, InlineKeyboardMarkup(kb)


def active_flow_running_screen(
    flow: dict[str, Any] | None,
    tasks: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    session: TelegramSession,
) -> tuple[str, InlineKeyboardMarkup]:
    """Estado del flow en ejecución + tareas + logs recientes."""
    title = flow.get("title") or flow.get("name") if flow else session.active_flow_id or "?"
    status = flow.get("status") if flow else session.active_flow_status or "unknown"
    parts = [
        f"⚙️ *Flow: {title}*",
        f"Estado: {status}",
        f"Tareas: {len(tasks)}",
    ]
    if logs:
        recent = logs[-3:]
        for entry in recent:
            msg = str(entry.get("message") or entry.get("content") or entry.get("text") or "")[:120]
            if msg:
                parts.append(f"> {msg}")
    text = truncate("\n".join(parts))
    kb = [
        [InlineKeyboardButton("🖥 Terminal", callback_data="ui:terminal"),
         InlineKeyboardButton("📋 Tareas", callback_data="ui:tasks")],
        [InlineKeyboardButton("📝 Logs", callback_data="ui:logs"),
         InlineKeyboardButton("🔍 Hallazgos", callback_data="ui:findings")],
        [InlineKeyboardButton("🛑 Detener", callback_data="ui:stop_flow"),
         InlineKeyboardButton("✉️ Enviar Input", callback_data="ui:input")],
        [InlineKeyboardButton("🔙 Home", callback_data="ui:home")],
    ]
    return text, InlineKeyboardMarkup(kb)


def flow_waiting_screen(flow: dict[str, Any] | None, session: TelegramSession) -> tuple[str, InlineKeyboardMarkup]:
    """PentAGI espera input del usuario."""
    title = flow.get("title") or flow.get("name") if flow else session.active_flow_id or "?"
    text = f"⏳ *{title}* espera tu input.\n\nEscribe tu respuesta ahora o usa los botones."
    kb = [
        [InlineKeyboardButton("✉️ Enviar Input", callback_data="ui:input")],
        [InlineKeyboardButton("🖥 Terminal", callback_data="ui:terminal"),
         InlineKeyboardButton("🔙 Home", callback_data="ui:home")],
    ]
    return text, InlineKeyboardMarkup(kb)


def flow_finished_screen(flow: dict[str, Any] | None, tasks: list[dict[str, Any]]) -> tuple[str, InlineKeyboardMarkup]:
    """Flow finalizado con reporte."""
    title = flow.get("title") or flow.get("name") if flow else "Flow"
    parts = [f"✅ *{title} completado*"]
    findings = [t for t in tasks if t.get("result") or t.get("content")]
    if findings:
        for f_item in findings[-5:]:
            snippet = redact(str(f_item.get("result") or f_item.get("content") or ""))[:160]
            parts.append(f"• {snippet}")
    text = truncate("\n".join(parts))
    kb = [
        [InlineKeyboardButton("📋 Hallazgos", callback_data="ui:findings")],
        [InlineKeyboardButton("📝 Resumen", callback_data="ui:summary"),
         InlineKeyboardButton("📊 Reporte", callback_data="ui:report")],
        [InlineKeyboardButton("✅ Nuevo Flow", callback_data="ui:new_flow"),
         InlineKeyboardButton("🔙 Home", callback_data="ui:home")],
    ]
    return text, InlineKeyboardMarkup(kb)


def assistant_screen(assistants: list[dict[str, Any]], logs: list[dict[str, Any]]) -> tuple[str, InlineKeyboardMarkup]:
    """Pantalla de asistente conversacional."""
    parts = ["💬 *Asistente*"]
    if logs:
        for entry in logs[-5:]:
            role = entry.get("role", "?")
            msg = str(entry.get("message") or entry.get("content") or "")[:120]
            parts.append(f"*{role}*: {msg}")
    else:
        parts.append("Escribe tu mensaje para el asistente.")
    text = truncate("\n".join(parts))
    kb = [
        [InlineKeyboardButton("🔙 Home", callback_data="ui:home")],
    ]
    return text, InlineKeyboardMarkup(kb)


def provider_select_screen(providers: list[dict[str, Any]], selected: str | None) -> tuple[str, InlineKeyboardMarkup]:
    """Lista seleccionable de providers."""
    if not providers:
        return "No hay providers disponibles.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Home", callback_data="ui:home")]])
    parts = ["🔌 *Selecciona un Provider:*"]
    parts.append(f"Actual: {selected or 'ninguno'}")
    text = "\n".join(parts)
    kb = []
    for p in providers:
        name = provider_label(p)
        button_text = f"{'✅ ' if name == selected else '➡️ '}{name}"
        kb.append([InlineKeyboardButton(button_text, callback_data=f"ui:select_provider:{name}")])
    kb.append([InlineKeyboardButton("🔙 Home", callback_data="ui:home")])
    return text, InlineKeyboardMarkup(kb)


def template_select_screen(templates: list[dict[str, Any]], selected: str | None) -> tuple[str, InlineKeyboardMarkup]:
    """Lista seleccionable de templates."""
    parts = ["📝 *Selecciona un Template:*"]
    parts.append(f"Actual: {selected or 'ninguno'}")
    text = "\n".join(parts)
    kb = []
    for t in templates:
        tid = str(t.get("id") or t.get("name") or "?")
        label = str(t.get("name") or t.get("title") or tid)[:32]
        button_text = f"{'✅ ' if tid == selected else '➡️ '}{label}"
        kb.append([InlineKeyboardButton(button_text, callback_data=f"ui:select_template:{tid}")])
    kb.append([InlineKeyboardButton("🔙 Home", callback_data="ui:home")])
    return text, InlineKeyboardMarkup(kb)


def error_screen(error_msg: str) -> str:
    """Mensaje de error limpio sin traceback."""
    safe = redact(str(error_msg))[:300]
    return f"⚠️ *Error*\n{safe}\n\nSi el problema persiste contacta al administrador."


# ---------------------------------------------------------------------------
# Legacy formatters — kept for callers that still reference them by name
# ---------------------------------------------------------------------------


def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Ver flows", callback_data="ui:list_flows"),
                InlineKeyboardButton("Estado gateway", callback_data="ui:gateway_status"),
            ],
            [
                InlineKeyboardButton("Providers", callback_data="ui:providers"),
                InlineKeyboardButton("Ayuda", callback_data="ui:help"),
            ],
            [
                InlineKeyboardButton("Estado flow", callback_data="ui:active_status"),
                InlineKeyboardButton("Resumen", callback_data="ui:summary"),
            ],
            [InlineKeyboardButton("Tareas", callback_data="ui:tasks"), InlineKeyboardButton("Enviar instrucción", callback_data="ui:send_input_help")],
            [
                InlineKeyboardButton("Logs", callback_data="ui:logs"),
                InlineKeyboardButton("Terminal", callback_data="ui:terminal"),
            ],
            [
                InlineKeyboardButton("Hallazgos", callback_data="ui:findings"),
                InlineKeyboardButton("Stop local", callback_data="ui:stop_local"),
            ],
        ]
    )


def no_active_flow_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Ver flows", callback_data="ui:list_flows"), InlineKeyboardButton("Ayuda", callback_data="ui:help")]]
    )


def error_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Ayuda", callback_data="ui:help"), InlineKeyboardButton("Flows", callback_data="ui:list_flows")]])


def stop_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Detener operación local", callback_data="ui:stop_local")]])


def flow_actions_markup(flow_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Estado", callback_data=f"flow:status:{flow_id}"), InlineKeyboardButton("Resumen", callback_data=f"flow:summary:{flow_id}")],
            [InlineKeyboardButton("Tareas", callback_data=f"flow:tasks:{flow_id}"), InlineKeyboardButton("Logs", callback_data=f"flow:logs:{flow_id}")],
            [InlineKeyboardButton("Terminal", callback_data=f"flow:terminal:{flow_id}"), InlineKeyboardButton("Hallazgos", callback_data=f"flow:findings:{flow_id}")],
            [InlineKeyboardButton("Enviar instrucción", callback_data=f"flow:send_help:{flow_id}"), InlineKeyboardButton("Stop local", callback_data="ui:stop_local")],
            [InlineKeyboardButton("Watch", callback_data=f"flow:watch:{flow_id}"), InlineKeyboardButton("Ayuda", callback_data="ui:help")],
        ]
    )


def flows_markup(flows: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for flow in flows[:8]:
        flow_id = str(flow.get("id") or "")
        if flow_id.isdigit():
            label = str(flow.get("title") or flow.get("name") or flow_id)[:32]
            rows.append([InlineKeyboardButton(f"Abrir {label}", callback_data=f"flow:bind:{flow_id}")])
    rows.append([InlineKeyboardButton("Ayuda", callback_data="ui:help")])
    return InlineKeyboardMarkup(rows)


def approval_markup(approval: Approval) -> InlineKeyboardMarkup:
    confirm = "approval:confirm_delete" if approval.confirm_delete else "approval:confirm"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Confirmar", callback_data=f"{confirm}:{approval.code}"), InlineKeyboardButton("Denegar", callback_data=f"approval:deny:{approval.code}")],
            [InlineKeyboardButton("Detalle", callback_data=f"approval:detail:{approval.code}")],
        ]
    )



def format_operator_intro() -> str:
    return (
        "Hola. Soy tu operador de PentAGI Gateway en Telegram. Trabajo con el contexto del flow activo: "
        "puedo ayudarte a elegir flows, revisar providers, resumen, tareas, logs, terminal y hallazgos. "
        "El gateway está en modo seguro: las instrucciones y acciones reales pasan por política y aprobación."
    )


def format_identity() -> str:
    return (
        "Soy PentAGI Gateway, una interfaz conversacional para operar PentAGI desde Telegram. "
        "Mi modelo mental es el de la UI: flow activo, providers, asistentes, eventos, logs y hallazgos. "
        "No ejecuto mutaciones directas en READ_ONLY."
    )


def format_no_active_flow_guidance() -> str:
    return NO_ACTIVE_FLOW_TEXT + " Usa los botones para ver flows o pedir ayuda."


def format_contextual_help() -> str:
    return (
        "Te ayudo como operador de PentAGI. Puedes preguntar: 'qué está haciendo', 'resume', "
        "'qué encontró', 'muéstrame logs' o 'abre flow 123'. Los comandos quedan como fallback técnico."
    )

def format_flow_list(flows: list[dict[str, Any]]) -> str:
    if not flows:
        return "No hay flows disponibles."
    lines = ["*PentAGI Flows:*"]
    for flow in flows:
        flow_id = str(flow.get("id", "?"))
        lines.append(
            f"• `{flow_id}` — *{flow.get('title') or flow.get('name', '?')}*\n"
            f"   Estado: {flow.get('status', '?')} | Provider: {provider_label(flow.get('provider'))}\n"
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
        f"Provider: {provider_label(flow.get('provider'))}\n"
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
    status_lower = str(status).lower()
    if any(x in status_lower for x in ("run", "running", "active", "working")):
        status_norm = "marcha"
    elif any(x in status_lower for x in ("wait", "waiting", "input", "paused")):
        status_norm = "READ_ONLY"
    elif any(x in status_lower for x in ("finish", "finished", "done", "stopped", "failed", "error")):
        status_norm = "reporte"
    else:
        status_norm = str(status)
    recent = " | ".join(redact(str(x.get("message") or x.get("content") or x.get("text") or x.get("result") or ""))[:90] for x in (logs[-3:] or tasks[-3:]))
    return truncate(f"Resumen de {title}: estado={status_norm}; tareas={len(tasks)}; reciente: {recent or 'sin actividad reciente'}")


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
        "Usa los botones para confirmar o denegar. Fallback: /confirm <code>, /confirm_delete <code> o /deny <code>."
    )


def format_mutation_result(action: str, result: dict[str, Any]) -> str:
    if action == "create_assistant":
        assistant = result.get("assistant", {})
        if assistant:
            return truncate(f"✅ Assistant creado:\nID: {assistant.get('id', 'N/A')}\nTitle: {assistant.get('title', 'N/A')}\nStatus: {assistant.get('status', 'N/A')}")
        return truncate(f"❌ Error creando assistant: {result}")
    if action == "call_assistant":
        if result.get("success"):
            output = result.get("output", "")
            msg = result.get("message", "")
            detail = f"✅ Assistant call ejecutado.\n{msg}" if msg else "✅ Assistant call ejecutado."
            if output:
                detail += f"\n\n{output[:500]}"
            return truncate(detail)
        return truncate(f"❌ Assistant call failed: {result}")
    if action == "stop_assistant":
        assistant = result.get("stopAssistant", result)
        if isinstance(assistant, dict) and assistant.get("id"):
            return truncate(f"✅ Assistant stopped: {assistant.get('title', 'N/A')}")
        return truncate(f"❌ Error stopping assistant: {result}")
    if action == "delete_assistant":
        status = result.get("deleteAssistant", "unknown")
        if status == "success":
            return "✅ Assistant deleted successfully."
        return f"❌ Delete assistant failed: {status}"
    return truncate(f"✅ Mutación ejecutada: {action}\n{result}")


def format_events(events: list[Any]) -> str:
    if not events:
        return "Sin eventos pendientes."
    return truncate("\n".join(f"• {getattr(e, 'name', '?')} flow={getattr(e, 'flow_id', '?')}" for e in events))


OPERATOR_INTRO_TEXT = (
    "Hola. Soy el operador de PentAGI Gateway en Telegram. Trabajo con el contexto activo como la UI de PentAGI: "
    "flows, providers, asistentes, logs, eventos y acciones según estado."
)
IDENTITY_TEXT = (
    "Soy PentAGI Gateway Operator: traduzco conversación natural de Telegram a acciones equivalentes de la UI de PentAGI, "
    "manteniendo contexto activo y aplicando política antes de cualquier acción sensible."
)
CAPABILITIES_TEXT = (
    "Puedo ayudarte a elegir un flow, revisar estado, tareas, resumen, logs, terminal y hallazgos; ver providers; "
    "y preparar instrucciones o acciones sensibles solo cuando el modo del Gateway y una aprobación explícita lo permitan."
)


def operator_intro() -> str:
    return OPERATOR_INTRO_TEXT + "\n\nElige una acción o dime qué necesitas en lenguaje natural."


def operator_identity() -> str:
    return IDENTITY_TEXT


def operator_capabilities() -> str:
    return CAPABILITIES_TEXT


def no_active_flow_guidance() -> str:
    return (
        "Ahora no tengo un flow activo seleccionado. Puedo mostrarte los flows disponibles "
        "para que elijas uno y desde ahí revisar estado, tareas, logs, hallazgos o resumen."
    )

def gateway_status_text(mode: str) -> str:
    if mode.upper() == "READ_ONLY":
        safety = "Modo READ_ONLY: puedo consultar y preparar contexto; las acciones sensibles están bloqueadas."
    elif mode.upper() == "ASSISTED_EXECUTION":
        safety = "Modo ASSISTED_EXECUTION: las acciones sensibles requieren aprobación explícita antes de llamar a PentAGI."
    else:
        safety = f"Modo {mode}: aplicaré la política configurada antes de actuar."
    return f"PentAGI Gateway está operativo. {safety}"


def send_input_help(mode: str) -> str:
    if mode.upper() == "READ_ONLY":
        return (
            "Puedo ayudarte a redactar una instrucción para el flow activo, pero enviarla a PentAGI está bloqueado en READ_ONLY. "
            "Para putUserInput se necesita ASSISTED_EXECUTION y aprobación."
        )
    return "Escribe algo como: 'dile que continúe con el análisis'. Antes de enviarlo, pediré aprobación."


def format_flow_state_summary(flow: dict[str, Any] | None, tasks: list[dict[str, Any]], logs: list[dict[str, Any]], mode: str = "READ_ONLY") -> str:
    if not flow:
        return "No encontré ese flow. Puedes volver a la lista y elegir otro."
    status_raw = str(flow.get("status") or flow.get("state") or "unknown")
    status = status_raw.lower()
    title = flow.get("title") or flow.get("name") or flow.get("id") or "flow"
    base = [f"Resumen del flow activo: {title}", f"Estado: {status_raw}", f"Tareas visibles: {len(tasks)}"]
    if any(x in status for x in ("run", "running", "active", "working", "created")):
        base.append("Está en marcha. Puedo resumir progreso, tareas, logs, terminal o hallazgos.")
    elif any(x in status for x in ("wait", "waiting", "input", "need", "paused")):
        if mode.upper() == "READ_ONLY":
            base.append("Parece estar esperando input. En READ_ONLY puedo ayudarte a redactarlo, pero enviarlo está bloqueado salvo ASSISTED_EXECUTION + aprobación.")
        else:
            base.append("Parece estar esperando input. Si quieres enviar una instrucción, pediré aprobación antes.")
    elif any(x in status for x in ("finish", "finished", "done", "stopped", "failed", "error")):
        base.append("Parece finalizado o detenido. Puedo preparar un reporte con resumen y hallazgos.")
    else:
        base.append("Puedo revisar detalle, tareas, logs o hallazgos para aclarar el estado.")
    recent = " | ".join(redact(str(x.get("message") or x.get("content") or x.get("text") or x.get("result") or ""))[:90] for x in logs[-3:])
    if recent:
        base.append(f"Reciente: {recent}")
    return truncate("\n".join(base))


def format_safe_error(exc: BaseException | str) -> str:
    text = redact(str(exc))
    lowered = text.lower()
    if "graphql" in lowered or "validation" in lowered or "parse" in lowered:
        detail = "PentAGI rechazó la consulta o el esquema no coincide con lo esperado. No se ejecutó ninguna acción."
    elif "401" in text or "token" in lowered or "unauthorized" in lowered or "auth" in lowered:
        detail = "No puedo autenticar contra PentAGI con la configuración actual. Revisa credenciales fuera del chat."
    elif "timeout" in lowered:
        detail = "PentAGI tardó demasiado en responder. No se ejecutó ninguna acción."
    else:
        detail = "No pude completar la consulta de forma segura. No se ejecutó ninguna acción."
    return f"⚠️ {detail}"
