from nekofetch.domain.enums import ROLE_PERMISSIONS, Permission, Role


def test_user_cannot_configure():
    assert Permission.CONFIGURE not in ROLE_PERMISSIONS[Role.USER]
    assert Permission.SUBMIT_REQUEST in ROLE_PERMISSIONS[Role.USER]


def test_staff_inherits_user():
    assert ROLE_PERMISSIONS[Role.USER] <= ROLE_PERMISSIONS[Role.STAFF]
    assert Permission.QUEUE_DOWNLOADS in ROLE_PERMISSIONS[Role.STAFF]
    assert Permission.GENERATE_BOTS not in ROLE_PERMISSIONS[Role.STAFF]


def test_admin_has_everything():
    assert ROLE_PERMISSIONS[Role.ADMIN] == set(Permission)
