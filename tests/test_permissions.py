import types

from nekofetch.domain.enums import ROLE_PERMISSIONS, Permission, Role
from nekofetch.services.auth_service import AuthService


def test_user_cannot_configure():
    assert Permission.CONFIGURE not in ROLE_PERMISSIONS[Role.USER]
    assert Permission.SUBMIT_REQUEST in ROLE_PERMISSIONS[Role.USER]


def test_staff_inherits_user():
    assert ROLE_PERMISSIONS[Role.USER] <= ROLE_PERMISSIONS[Role.STAFF]
    assert Permission.QUEUE_DOWNLOADS in ROLE_PERMISSIONS[Role.STAFF]
    assert Permission.GENERATE_BOTS not in ROLE_PERMISSIONS[Role.STAFF]


def test_admin_has_everything():
    assert ROLE_PERMISSIONS[Role.ADMIN] == set(Permission)


def _auth(owner_id: int, admin_ids: list[int]) -> AuthService:
    container = types.SimpleNamespace(
        env=types.SimpleNamespace(admin_ids=admin_ids),
        config=types.SimpleNamespace(security=types.SimpleNamespace(owner_id=owner_id)),
    )
    return AuthService(container)


def _user(tid: int):
    return types.SimpleNamespace(telegram_id=tid, role=Role.ADMIN, is_banned=False)


def test_owner_is_configured_id_when_set():
    auth = _auth(owner_id=111, admin_ids=[111, 222])
    assert auth.is_owner(_user(111)) is True
    # Another admin is NOT the owner — sensitive config stays with the owner.
    assert auth.is_owner(_user(222)) is False


def test_owner_falls_back_to_first_admin():
    auth = _auth(owner_id=0, admin_ids=[333, 444])
    assert auth.is_owner(_user(333)) is True
    assert auth.is_owner(_user(444)) is False
    assert auth.is_owner(None) is False


def test_sensitive_sections_are_owner_only():
    from nekofetch.core.settings_schema import is_owner_only
    for s in ("security", "sources", "storage_channel", "log_channel",
              "main_channel", "index_channel", "access", "shortlink"):
        assert is_owner_only(s), s
    for s in ("features", "downloads", "branding", "watermark", "ui"):
        assert not is_owner_only(s), s
