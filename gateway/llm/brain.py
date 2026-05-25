"""Natural-language brain.

LLM mode is a strict JSON classifier only. It never executes actions.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from .schemas import MUTATION_INTENTS, Intent, IntentDecision


NO_ACTIVE_FLOW_TEXT = "No tengo un flow activo seleccionado. Puedo mostrarte los flows disponibles."
UNKNOWN_GUIDANCE = "No entendí. Puedes pedirme: mostrar flows disponibles, abrir flow <id>, resumir el flow activo o revisar hallazgos."


class BrainContext:
    """Rich context for intent classification."""

    def __init__(
        self,
        text: str = "",
        flow_status: str | None = None,
        providers: list[dict[str, Any]] | None = None,
        assistants: list[dict[str, Any]] | None = None,
        tasks_count: int = 0,
        recent_logs: list[dict[str, Any]] | None = None,
        gateway_mode: str = "READ_ONLY",
        last_screen: str = "home",
        draft_message: str | None = None,
        selected_provider: str | None = None,
        selected_assistant_id: str | None = None,
        active_flow_id: str | None = None,
    ) -> None:
        self.text = text
        self.flow_status = flow_status
        self.providers = providers or []
        self.assistants = assistants or []
        self.tasks_count = tasks_count
        self.recent_logs = recent_logs or []
        self.gateway_mode = gateway_mode
        self.last_screen = last_screen
        self.draft_message = draft_message
        self.selected_provider = selected_provider
        self.selected_assistant_id = selected_assistant_id
        self.active_flow_id = active_flow_id


class Brain:
    """Classifies text into IntentDecision."""

    def __init__(
        self,
        enabled: bool = False,
        base_url: str = "http://localhost:8000/v1",
        api_key: str = "",
        model: str = "qwen",
    ) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def classify(self, text: str, active_flow_id: str | None = None, context: BrainContext | None = None) -> IntentDecision:
        if context is None:
            if active_flow_id:
                context = BrainContext(text=text, active_flow_id=active_flow_id)
            else:
                context = BrainContext(text=text)
        else:
            context.text = text
            if active_flow_id:
                context.active_flow_id = active_flow_id
        if self.enabled:
            return await self._classify_llm(text, active_flow_id, context)
        return self._classify_local(text, active_flow_id, context)

    async def _classify_llm(self, text: str, active_flow_id: str | None, context: BrainContext) -> IntentDecision:
        ctx_summary = (
            f"flow_status={context.flow_status!r}, "
            f"providers_count={len(context.providers)}, "
            f"assistants_count={len(context.assistants)}, "
            f"tasks_count={context.tasks_count}, "
            f"gateway_mode={context.gateway_mode!r}, "
            f"last_screen={context.last_screen!r}, "
            f"has_draft={context.draft_message is not None}"
        )
        prompt = (
            "Return ONLY JSON matching: intent,risk,requires_confirmation,flow_ref,action,user_response,parameters. "
            "Never execute. Mutation intents require confirmation. "
            f"Text: {text!r}; active_flow_id={active_flow_id!r}; context: {ctx_summary}"
        )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a strict JSON intent classifier."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                decision = IntentDecision.model_validate(parsed).normalized()
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError, ValidationError, ValueError):
            return IntentDecision(intent=Intent.UNKNOWN, user_response=UNKNOWN_GUIDANCE)
        if decision.intent not in Intent:
            return IntentDecision(intent=Intent.UNKNOWN, user_response=UNKNOWN_GUIDANCE)
        return _enforce_safety(decision)

    def _classify_local(self, text: str, active_flow_id: str | None, context: BrainContext) -> IntentDecision:
        t = text.strip()
        low = t.lower()
        flow_id = _extract_flow_id(t) or active_flow_id
        if not t:
            return IntentDecision(intent=Intent.UNKNOWN, user_response="¿Qué necesitas hacer?")

        # --- UI state commands (new intents) ---
        if any(x in low for x in ("ayuda", "help", "/help")):
            if context.last_screen and context.last_screen != "home":
                return IntentDecision(intent=Intent.HELP_UI, parameters={"screen": context.last_screen})
            return IntentDecision(intent=Intent.HELP)

        if "seleccionar proveedor" in low or "selecciona proveedor" in low:
            return IntentDecision(intent=Intent.SET_PROVIDER, parameters={"provider": _extract_provider(t)})
        if "proveedor" in low or "providers" in low:
            return IntentDecision(intent=Intent.LIST_PROVIDERS)
        if "plantilla" in low or "template" in low:
            return IntentDecision(intent=Intent.APPLY_TEMPLATE, parameters={"template_id": _extract_template_id(t)})

        # Flow listing / status
        if "muéstrame los flows" in low or "lista flows" in low or "flujos" in low or "flows" in low:
            return IntentDecision(intent=Intent.LIST_FLOWS)
        if "tareas" in low or "task" in low:
            return IntentDecision(intent=Intent.GET_TASKS)
        if any(x in low for x in ("abre este flow", "abre flow", "abrir flow", "bind", "vincula")) and flow_id:
            return IntentDecision(intent=Intent.BIND_FLOW, flow_ref=flow_id)
        if any(x in low for x in ("qué está haciendo", "que esta haciendo", "estado", "status")):
            if flow_id:
                return IntentDecision(intent=Intent.GET_FLOW_STATUS, flow_ref=flow_id)
            return IntentDecision(intent=Intent.UNKNOWN, user_response=NO_ACTIVE_FLOW_TEXT)

        # Draft / new flow
        if any(x in low for x in ("nuevo flow", "nuevo flujo", "crea", "crear flow", "nuevo objetivo", "new flow", "empezar")):
            return IntentDecision(intent=Intent.SUBMIT_DRAFT, action="create_flow", parameters={"prompt": t})

        # Terminal / assistant views
        if "logs" in low or "mensaje" in low or "mensajes" in low:
            return IntentDecision(intent=Intent.GET_LOGS)
        if "terminal" in low or "consola" in low:
            return IntentDecision(intent=Intent.VIEW_TERMINAL, flow_ref=flow_id or context.active_flow_id)
        if "envía al assistant" in low or "envia al assistant" in low or "pregunta al assistant" in low:
            return IntentDecision(intent=Intent.SEND_ASSISTANT_MESSAGE, action="call_assistant", parameters={"message": t})
        if any(x in low for x in ("asistente", "assistant", "ver assistant", "assistant mode")):
            return IntentDecision(intent=Intent.VIEW_ASSISTANT)

        # Existing intents (maintain backward compat)
        if "resume" in low or "resumen" in low or "summary" in low:
            if flow_id:
                return IntentDecision(intent=Intent.GET_FLOW_SUMMARY, flow_ref=flow_id)
            return IntentDecision(intent=Intent.UNKNOWN, user_response=NO_ACTIVE_FLOW_TEXT)
        if "qué encontró" in low or "que encontro" in low or "hallazgo" in low or "finding" in low:
            if flow_id:
                return IntentDecision(intent=Intent.GET_RECENT_FINDINGS, flow_ref=flow_id)
            return IntentDecision(intent=Intent.UNKNOWN, user_response=NO_ACTIVE_FLOW_TEXT)
        if "crea" in low and "flow" in low:
            return _enforce_safety(IntentDecision(intent=Intent.CREATE_FLOW_REQUEST, action="create_flow", parameters={"prompt": t}))
        if any(x in low for x in ("dile que", "envía", "envia", "continúe", "continue", "send")):
            if flow_id:
                return _enforce_safety(IntentDecision(intent=Intent.SEND_USER_INPUT_REQUEST, flow_ref=flow_id, action="put_user_input", parameters={"input": t}))
            return IntentDecision(intent=Intent.UNKNOWN, user_response=NO_ACTIVE_FLOW_TEXT)
        if any(x in low for x in ("detén", "deten", "stop", "para todo")):
            if flow_id:
                return _enforce_safety(IntentDecision(intent=Intent.STOP_FLOW_REQUEST, flow_ref=flow_id, action="stop_flow"))
            return IntentDecision(intent=Intent.UNKNOWN, user_response=NO_ACTIVE_FLOW_TEXT)
        if "finish" in low or "finaliza" in low:
            if flow_id:
                return _enforce_safety(IntentDecision(intent=Intent.FINISH_FLOW_REQUEST, flow_ref=flow_id, action="finish_flow"))
            return IntentDecision(intent=Intent.UNKNOWN, user_response=NO_ACTIVE_FLOW_TEXT)
        if "renombra" in low or "rename" in low:
            if flow_id:
                return _enforce_safety(IntentDecision(intent=Intent.RENAME_FLOW_REQUEST, flow_ref=flow_id, action="rename_flow", parameters={"name": t}))
            return IntentDecision(intent=Intent.UNKNOWN, user_response=NO_ACTIVE_FLOW_TEXT)
        if "delete" in low or "borra" in low or "elimina" in low:
            return _enforce_safety(IntentDecision(intent=Intent.DELETE_FLOW_REQUEST, flow_ref=flow_id, action="delete_flow"))
        # SMALLTALK: saludos, agradecimientos, charla informal
        smalltalk_keywords = ["hola","buenas","buen día","buenas tardes","gracias","ok","okey","vale","de acuerdo","perfecto","listo","cómo estás","qué tal","bien y tú","hey","oye","saludos"]
        if any(k in low for k in smalltalk_keywords):
            return IntentDecision(intent=Intent.GREETING, user_response="¡Hola! Bienvenido, operador. PentAGI Gateway listo.")
        if any(x in low for x in ("quién eres", "que eres", "identity", "about you")):
            return IntentDecision(intent=Intent.OPERATOR_IDENTITY, user_response="Soy PentAGI Gateway, tu asistente de orquestación de flows de ciberseguridad.")
        if any(x in low for x in ("qué puedes hacer", "que puedes hacer", "capabilities", "features")):
            return IntentDecision(intent=Intent.OPERATOR_CAPABILITIES, user_response="Puedo listar flows, activar/proveedores, crear flows, enviar inputs, ver logs, terminal y resumir hallazgos.")
        if any(x in low for x in ("qué haces", "que haces", "intro", "introducción", "introduccion")):
            return IntentDecision(intent=Intent.OPERATOR_INTRO)
        return IntentDecision(intent=Intent.UNKNOWN, user_response=UNKNOWN_GUIDANCE)


def _extract_flow_id(text: str) -> str | None:
    """Extract only explicit numeric flow IDs; never infer normal words."""
    patterns = (
        r"\b(?:flow|flujo|flow_id|id)\s*[:#=]?\s*(\d+)\b",
        r"\b(?:flow|flujo)\s+(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_provider(text: str) -> str:
    """Extract provider name from text."""
    match = re.search(r"(?:proveedor|provider)\s*[:#=]?\s*(\w+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    # Try to find a known provider name
    for word in ("qwen", "openai", "anthropic", "gemini", "ollama", "custom", "deepseek", "azure"):
        if word in text.lower():
            return word
    return ""


def _extract_template_id(text: str) -> str:
    match = re.search(r"(?:plantilla|template)\s*[:#=]?\s*([\w-]+)", text, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _enforce_safety(decision: IntentDecision) -> IntentDecision:
    if decision.intent in MUTATION_INTENTS:
        decision.requires_confirmation = True
        if decision.intent == Intent.DELETE_FLOW_REQUEST:
            decision.risk = "CRITICAL"
        elif decision.risk.upper() not in {"HIGH", "CRITICAL"}:
            decision.risk = "HIGH"
    return decision.normalized()
