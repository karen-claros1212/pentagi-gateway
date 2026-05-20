"""Authentication & role-based access control."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    READONLY = "readonly"


@dataclass
class AuthContext:
    user_id: int
    chat_id: int
    username: str | None = None
    role: Role = Role.READONLY


class AuthProvider:
    """Allowlist-based authorization with role resolution."""

    def __init__(
        self,
        allowed_users: list[int],
        allowed_chats: list[int] | None = None,
        admins: list[int] | None = None,
        operators: list[int] | None = None,
    ) -> None:
        self._allowed_users = set(allowed_users)
        self._allowed_chats = set(allowed_chats) if allowed_chats else set()
        self._admins = set(admins) if admins else set()
        self._operators = set(operators) if operators else set()

    def is_authorized(self, user_id: int, chat_id: int | None = None) -> bool:
        return user_id in self._allowed_users or bool(
            self._allowed_chats and chat_id and chat_id in self._allowed_chats
        )

    def resolve_role(self, user_id: int) -> Role:
        if user_id in self._admins:
            return Role.ADMIN
        if user_id in self._operators:
            return Role.OPERATOR
        return Role.READONLY

    def build_context(self, user_id: int, chat_id: int, username: str | None = None) -> AuthContext:
        return AuthContext(user_id=user_id, chat_id=chat_id, username=username, role=self.resolve_role(user_id))
