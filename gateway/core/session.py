"""Session persistence via SQLite."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from ..core.auth import Role


@dataclass
class TelegramSession:
    chat_id: int
    user_id: int
    role: str = "readonly"
    active_flow_id: Optional[str] = None
    mode: str = "READ_ONLY"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class AuditEvent:
    id: int = 0
    user_id: int = 0
    chat_id: int = 0
    action: str = ""
    risk: str = "low"
    allowed: bool = True
    reason: str = ""
    created_at: float = field(default_factory=time.time)


class SessionStore:
    """SQLite-based session and audit storage."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def open(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS telegram_sessions (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'readonly',
                active_flow_id TEXT,
                mode TEXT NOT NULL DEFAULT 'READ_ONLY',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                risk TEXT NOT NULL DEFAULT 'low',
                allowed INTEGER NOT NULL DEFAULT 1,
                reason TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rate_limits (
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                window_start REAL NOT NULL,
                counter INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, action, window_start)
            );
            """
        )
        await self._conn.commit()

    async def close(self) -> None:
        if hasattr(self, "_conn"):
            await self._conn.close()

    async def get_session(self, chat_id: int, user_id: int) -> Optional[TelegramSession]:
        row = await self._conn.execute(
            "SELECT * FROM telegram_sessions WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        r = await row.fetchone()
        if r is None:
            return None
        return TelegramSession(**dict(r))

    async def upsert_session(self, session: TelegramSession) -> None:
        session.updated_at = time.time()
        await self._conn.execute(
            """INSERT INTO telegram_sessions (chat_id, user_id, role, active_flow_id, mode, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chat_id, user_id) DO UPDATE SET
                   role=excluded.role,
                   active_flow_id=excluded.active_flow_id,
                   mode=excluded.mode,
                   updated_at=excluded.updated_at""",
            (
                session.chat_id,
                session.user_id,
                session.role,
                session.active_flow_id,
                session.mode,
                session.created_at,
                session.updated_at,
            ),
        )
        await self._conn.commit()

    async def bind_flow(self, chat_id: int, user_id: int, flow_id: str) -> None:
        await self._conn.execute(
            "UPDATE telegram_sessions SET active_flow_id = ?, updated_at = ? WHERE chat_id = ? AND user_id = ?",
            (flow_id, time.time(), chat_id, user_id),
        )
        await self._conn.commit()

    async def audit(
        self,
        user_id: int,
        chat_id: int,
        action: str,
        risk: str = "low",
        allowed: bool = True,
        reason: str = "",
    ) -> int:
        c = await self._conn.execute(
            "INSERT INTO audit_events (user_id, chat_id, action, risk, allowed, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, action, risk, 1 if allowed else 0, reason, time.time()),
        )
        await self._conn.commit()
        return c.lastrowid or 0
