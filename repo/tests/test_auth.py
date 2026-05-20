"""Test auth provider."""

from gateway.core.auth import AuthProvider, Role


def test_authorized_user():
    auth = AuthProvider(allowed_users=[123])
    assert auth.is_authorized(123)
    assert not auth.is_authorized(999)


def test_authorized_chat():
    auth = AuthProvider(allowed_users=[], allowed_chats=[-100])
    assert auth.is_authorized(999, -100)
    assert not auth.is_authorized(999, 111)


def test_resolve_role():
    auth = AuthProvider(allowed_users=[1], admins=[10], operators=[5])
    assert auth.resolve_role(10) == Role.ADMIN
    assert auth.resolve_role(5) == Role.OPERATOR
    assert auth.resolve_role(1) == Role.READONLY
    assert auth.resolve_role(99) == Role.READONLY


def test_build_context():
    auth = AuthProvider(allowed_users=[1])
    ctx = auth.build_context(1, -100, "alice")
    assert ctx.user_id == 1
    assert ctx.chat_id == -100
    assert ctx.username == "alice"
    assert ctx.role == Role.READONLY
