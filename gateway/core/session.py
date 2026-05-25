"""Session persistence via SQLite."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from .interfaces import ISessionStore


@dataclass
class TelegramSession:
    chat_id: int
    user_id: int
    role: str = "readonly"
    active_flow_id: str | None = None
    mode: str = "READ_ONLY"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # UI state fields (patch 8 + state machine)
    ui_mode: str = "home"  # "home" | "readonly" | "assistant" | "flow_draft" | "flow_control"
    active_flow_status: str | None = None
    selected_provider: str | None = None
    active_assistant_id: str | None = None  # Real assistant ID from createAssistant
    assistant_use_agents: bool = False  # Whether assistant uses agents mode
    selected_assistant_id: str | None = None  # Legacy: selected from list
    assistant_approved: bool = False  # Assistant session approved (allows callAssistant)
    assistant_approval_scope: str | None = None  # "assistant_session" or None
    assistant_approval_expires: float | None = None  # timestamp
    draft_message: str | None = None
    draft_template_id: str | None = None
    last_screen: str = "home"
    last_snapshot_at: float | None = None


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


class SessionStore(ISessionStore):
    """SQLite-based session, audit, rate-limit and approval storage."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SessionStore is not open")
        return self._conn

    async def open(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS telegram_sessions (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'readonly',
                active_flow_id TEXT,
                mode TEXT NOT NULL DEFAULT 'READ_ONLY',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                ui_mode TEXT NOT NULL DEFAULT 'home',
                active_flow_status TEXT,
                selected_provider TEXT,
                active_assistant_id TEXT,
                assistant_use_agents INTEGER NOT NULL DEFAULT 0,
                assistant_approved INTEGER NOT NULL DEFAULT 0,
                assistant_approval_scope TEXT,
                assistant_approval_expires REAL,
                selected_assistant_id TEXT,
                draft_message TEXT,
                draft_template_id TEXT,
                last_screen TEXT NOT NULL DEFAULT 'home',
                last_snapshot_at REAL,
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
            CREATE TABLE IF NOT EXISTS pending_approvals (
                approval_id TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                risk TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                confirm_delete INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                used_at REAL
            );
            """
        )
        # Migration: add UI columns if missing (backward compat)
        await self._migrate_ui_fields()
        await self.conn.commit()

    async def _migrate_ui_fields(self) -> None:
        """Add UI state columns on existing tables if they don't exist."""
        existing_cols = set()
        cursor = await self.conn.execute("PRAGMA table_info(telegram_sessions)")
        for row in await cursor.fetchall():
            existing_cols.add(row["name"])
        ui_columns = {
            "ui_mode": "TEXT NOT NULL DEFAULT 'home'",
            "active_flow_status": "TEXT",
            "selected_provider": "TEXT",
            "active_assistant_id": "TEXT",
            "assistant_use_agents": "INTEGER NOT NULL DEFAULT 0",
            "assistant_approved": "INTEGER NOT NULL DEFAULT 0",
            "assistant_approval_scope": "TEXT",
            "assistant_approval_expires": "REAL",
            "selected_assistant_id": "TEXT",
            "draft_message": "TEXT",
            "draft_template_id": "TEXT",
            "last_screen": "TEXT NOT NULL DEFAULT 'home'",
            "last_snapshot_at": "REAL",
        }
        for col_name, col_type in ui_columns.items():
            if col_name not in existing_cols:
                await self.conn.execute(
                    f"ALTER TABLE telegram_sessions ADD COLUMN {col_name} {col_type}"
                )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def get_session(self, chat_id: int, user_id: int) -> TelegramSession | None:
        cursor = await self.conn.execute(
            "SELECT * FROM telegram_sessions WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        row = await cursor.fetchone()
        return None if row is None else TelegramSession(**dict(row))

    async def ensure_session(self, chat_id: int, user_id: int, role: str = "readonly") -> TelegramSession:
        existing = await self.get_session(chat_id, user_id)
        if existing:
            return existing
        session = TelegramSession(chat_id=chat_id, user_id=user_id, role=role)
        await self.upsert_session(session)
        return session

    async def upsert_session(self, session: TelegramSession) -> None:
        session.updated_at = time.time()
        await self.conn.execute(
            """INSERT INTO telegram_sessions (
                   chat_id, user_id, role, active_flow_id, mode,
                   created_at, updated_at,
                   ui_mode, active_flow_status, selected_provider,
                   active_assistant_id, assistant_use_agents, assistant_approved,
                   assistant_approval_scope, assistant_approval_expires,
                   selected_assistant_id,
                   draft_message, draft_template_id, last_screen, last_snapshot_at
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chat_id, user_id) DO UPDATE SET
                   role=excluded.role,
                   active_flow_id=excluded.active_flow_id,
                   mode=excluded.mode,
                   updated_at=excluded.updated_at,
                   ui_mode=excluded.ui_mode,
                   active_flow_status=excluded.active_flow_status,
                   selected_provider=excluded.selected_provider,
                   active_assistant_id=excluded.active_assistant_id,
                   assistant_use_agents=excluded.assistant_use_agents,
                   assistant_approved=excluded.assistant_approved,
                   assistant_approval_scope=excluded.assistant_approval_scope,
                   assistant_approval_expires=excluded.assistant_approval_expires,
                   selected_assistant_id=excluded.selected_assistant_id,
                   draft_message=excluded.draft_message,
                   draft_template_id=excluded.draft_template_id,
                   last_screen=excluded.last_screen,
                   last_snapshot_at=excluded.last_snapshot_at""",
            (
                session.chat_id,
                session.user_id,
                session.role,
                session.active_flow_id,
                session.mode,
                session.created_at,
                session.updated_at,
                session.ui_mode,
                session.active_flow_status,
                session.selected_provider,
                session.active_assistant_id,
                1 if session.assistant_use_agents else 0,
                1 if session.assistant_approved else 0,
                session.assistant_approval_scope,
                session.assistant_approval_expires,
                session.selected_assistant_id,
                session.draft_message,
                session.draft_template_id,
                session.last_screen,
                session.last_snapshot_at,
            ),
        )
        await self.conn.commit()

    async def bind_flow(self, chat_id: int, user_id: int, flow_id: str) -> None:
        session = await self.ensure_session(chat_id, user_id)
        session.active_flow_id = flow_id
        await self.upsert_session(session)

    async def audit(
        self,
        user_id: int,
        chat_id: int,
        action: str,
        risk: str = "low",
        allowed: bool = True,
        reason: str = "",
    ) -> int:
        cursor = await self.conn.execute(
            "INSERT INTO audit_events (user_id, chat_id, action, risk, allowed, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, action, risk, 1 if allowed else 0, reason, time.time()),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def fetch_audit_actions(self) -> list[str]:
        cursor = await self.conn.execute("SELECT action FROM audit_events ORDER BY id")
        rows = await cursor.fetchall()
        return [str(row["action"]) for row in rows]

    async def approval_rows(self) -> list[dict[str, Any]]:
        cursor = await self.conn.execute("SELECT * FROM pending_approvals ORDER BY created_at")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
