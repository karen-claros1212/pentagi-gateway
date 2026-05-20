"""SQLite-backed human-in-the-loop approvals."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from .session import SessionStore


@dataclass
class Approval:
    approval_id: str
    code: str
    user_id: int
    chat_id: int
    action: str
    risk: str
    payload: dict[str, Any]
    payload_hash: str
    status: str
    confirm_delete: bool
    created_at: float
    expires_at: float


@dataclass
class ApprovalResult:
    ok: bool
    message: str
    approval: Approval | None = None


class ApprovalStore:
    """One-use approval records bound to user/chat and payload hash."""

    def __init__(self, store: SessionStore, ttl_seconds: int = 300) -> None:
        self.store = store
        self.ttl_seconds = ttl_seconds

    async def create(
        self,
        user_id: int,
        chat_id: int,
        action: str,
        risk: str,
        payload: dict[str, Any],
        confirm_delete: bool = False,
    ) -> Approval:
        approval_id = secrets.token_urlsafe(9)
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = time.time()
        payload_json = _stable_json(payload)
        payload_hash = _payload_hash(payload)
        await self.store.conn.execute(
            """INSERT INTO pending_approvals
               (approval_id, code, user_id, chat_id, action, risk, payload_json, payload_hash, status, confirm_delete, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (
                approval_id,
                code,
                user_id,
                chat_id,
                action,
                risk,
                payload_json,
                payload_hash,
                1 if confirm_delete else 0,
                now,
                now + self.ttl_seconds,
            ),
        )
        await self.store.conn.commit()
        await self.store.audit(user_id, chat_id, "approval_created", risk=risk, allowed=True, reason=action)
        return Approval(approval_id, code, user_id, chat_id, action, risk, payload, payload_hash, "pending", confirm_delete, now, now + self.ttl_seconds)

    async def get_by_code(self, code: str) -> Approval | None:
        cursor = await self.store.conn.execute(
            "SELECT * FROM pending_approvals WHERE code = ? ORDER BY created_at DESC LIMIT 1",
            (code,),
        )
        row = await cursor.fetchone()
        return None if row is None else _row_to_approval(dict(row))

    async def deny(self, code: str, user_id: int, chat_id: int) -> ApprovalResult:
        approval = await self.get_by_code(code)
        if approval is None:
            return ApprovalResult(False, "Aprobación no encontrada.")
        if approval.user_id != user_id or approval.chat_id != chat_id:
            return ApprovalResult(False, "Aprobación no pertenece a este usuario/chat.")
        await self._set_status(approval, "denied")
        await self.store.audit(user_id, chat_id, "approval_denied", risk=approval.risk, allowed=True, reason=approval.action)
        return ApprovalResult(True, "Aprobación denegada.", approval)

    async def confirm(
        self,
        code: str,
        user_id: int,
        chat_id: int,
        payload: dict[str, Any] | None = None,
        require_delete: bool = False,
        allow_delete: bool = False,
    ) -> ApprovalResult:
        approval = await self.get_by_code(code)
        if approval is None:
            return ApprovalResult(False, "Aprobación no encontrada.")
        if approval.user_id != user_id or approval.chat_id != chat_id:
            return ApprovalResult(False, "Aprobación no pertenece a este usuario/chat.")
        if approval.status != "pending":
            return ApprovalResult(False, "Aprobación ya usada o cerrada.")
        if approval.expires_at < time.time():
            await self._set_status(approval, "expired")
            await self.store.audit(user_id, chat_id, "approval_expired", risk=approval.risk, allowed=False, reason=approval.action)
            return ApprovalResult(False, "Aprobación expirada.")
        if approval.confirm_delete and not require_delete:
            return ApprovalResult(False, "deleteFlow requiere /confirm-delete <code>.")
        if require_delete and (not approval.confirm_delete or not allow_delete):
            return ApprovalResult(False, "confirm-delete no permitido para esta aprobación.")
        if payload is not None and _payload_hash(payload) != approval.payload_hash:
            return ApprovalResult(False, "Payload cambió; aprobación inválida.")
        await self._set_status(approval, "confirmed", used=True)
        await self.store.audit(user_id, chat_id, "approval_confirmed", risk=approval.risk, allowed=True, reason=approval.action)
        approval.status = "confirmed"
        return ApprovalResult(True, "Aprobación confirmada.", approval)

    async def _set_status(self, approval: Approval, status: str, used: bool = False) -> None:
        await self.store.conn.execute(
            "UPDATE pending_approvals SET status = ?, used_at = ? WHERE approval_id = ?",
            (status, time.time() if used else None, approval.approval_id),
        )
        await self.store.conn.commit()


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _row_to_approval(row: dict[str, Any]) -> Approval:
    return Approval(
        approval_id=row["approval_id"],
        code=row["code"],
        user_id=row["user_id"],
        chat_id=row["chat_id"],
        action=row["action"],
        risk=row["risk"],
        payload=json.loads(row["payload_json"]),
        payload_hash=row["payload_hash"],
        status=row["status"],
        confirm_delete=bool(row["confirm_delete"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )
