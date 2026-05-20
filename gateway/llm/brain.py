"""Natural-language brain.

LLM mode is a strict JSON classifier only. It never executes actions.
"""

from __future__ import annotations

import json
import re

import httpx
from pydantic import ValidationError

from .schemas import MUTATION_INTENTS, Intent, IntentDecision


NO_ACTIVE_FLOW_TEXT = "No tengo un flow activo seleccionado. Puedo mostrarte los flows disponibles."
UNKNOWN_GUIDANCE = "No entendí. Puedes pedirme: mostrar flows, abrir flow <id>, resumir el flow activo o revisar hallazgos."


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

    async def classify(self, text: str, active_flow_id: str | None = None) -> IntentDecision:
        if self.enabled:
            return await self._classify_llm(text, active_flow_id)
        return self._classify_local(text, active_flow_id)

    async def _classify_llm(self, text: str, active_flow_id: str | None) -> IntentDecision:
        prompt = (
            "Return ONLY JSON matching: intent,risk,requires_confirmation,flow_ref,action,user_response,parameters. "
            "Never execute. Mutation intents require confirmation. Text: "
            f"{text!r}; active_flow_id={active_flow_id!r}"
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

    def _classify_local(self, text: str, active_flow_id: str | None) -> IntentDecision:
        t = text.strip()
        low = t.lower()
        flow_id = _extract_flow_id(t) or active_flow_id
        if not t:
            return IntentDecision(intent=Intent.UNKNOWN, user_response="¿Qué necesitas hacer?")
        if any(w in low for w in ("ayuda", "help", "/help")):
            return IntentDecision(intent=Intent.HELP)
        if "proveedor" in low or "providers" in low:
            return IntentDecision(intent=Intent.LIST_PROVIDERS)
        if "muéstrame los flows" in low or "lista flows" in low or "flujos" in low or "flows" in low:
            return IntentDecision(intent=Intent.LIST_FLOWS)
        if any(x in low for x in ("abre este flow", "abre flow", "abrir flow", "bind", "vincula")) and flow_id:
            return IntentDecision(intent=Intent.BIND_FLOW, flow_ref=flow_id)
        if any(x in low for x in ("qué está haciendo", "que esta haciendo", "estado", "status")):
            if flow_id:
                return IntentDecision(intent=Intent.GET_FLOW_STATUS, flow_ref=flow_id)
            return IntentDecision(intent=Intent.UNKNOWN, user_response=NO_ACTIVE_FLOW_TEXT)
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


def _enforce_safety(decision: IntentDecision) -> IntentDecision:
    if decision.intent in MUTATION_INTENTS:
        decision.requires_confirmation = True
        if decision.intent == Intent.DELETE_FLOW_REQUEST:
            decision.risk = "CRITICAL"
        elif decision.risk.upper() not in {"HIGH", "CRITICAL"}:
            decision.risk = "HIGH"
    return decision.normalized()
