"""Audit log helpers."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AuditLogger:
    """Structured audit logging (Phase 2 — db-backed)."""

    @staticmethod
    def log(
        action: str,
        user_id: int,
        chat_id: int,
        risk: str = "low",
        allowed: bool = True,
        reason: str = "",
    ) -> None:
        logger.info(
            "AUDIT action=%s user=%d chat=%d risk=%s allowed=%s reason=%s",
            action, user_id, chat_id, risk, allowed, reason,
        )
