import uuid

import pytest

from app.models.user import User
from app.models.workspace import WorkspaceRole
from app.services.tenancy_service import TenancyService


def _user(db) -> User:
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@t.local", hashed_password="x")
    db.add(user)
    db.flush()
    return user


def test_slug_is_lowercased_and_hyphenated(db):
    assert TenancyService(db).generate_slug("Acme Corp") == "acme-corp"


def test_slug_strips_punctuation(db):
    assert TenancyService(db).generate_slug("Acme, Inc.!") == "acme-inc"


def test_slug_collision_gets_numeric_suffix(db):
    service = TenancyService(db)
    owner = _user(db)
    service.create_workspace("Dupe Test Co", owner)
    db.flush()
    assert service.generate_slug("Dupe Test Co") == "dupe-test-co-2"


def test_blank_slug_falls_back(db):
    assert TenancyService(db).generate_slug("!!!").startswith("workspace")


def test_validate_workspace_name_strips_and_returns(db):
    from app.services.tenancy_service import validate_workspace_name

    assert validate_workspace_name("  Acme Corp  ") == "Acme Corp"


def test_validate_workspace_name_rejects_angle_brackets(db):
    from app.core.errors import ConflictError
    from app.services.tenancy_service import validate_workspace_name

    with pytest.raises(ConflictError) as exc:
        validate_workspace_name('<img src=x onerror="alert(1)">')
    assert exc.value.code == "invalid_workspace_name"


def test_validate_workspace_name_rejects_empty_and_overlong(db):
    import pytest as _pytest

    from app.core.errors import ConflictError
    from app.services.tenancy_service import validate_workspace_name

    for bad in ("", "   ", "x" * 101):
        with _pytest.raises(ConflictError):
            validate_workspace_name(bad)


def test_validate_workspace_name_allows_ordinary_punctuation(db):
    from app.services.tenancy_service import validate_workspace_name

    assert validate_workspace_name("O'Brien & Sons, Inc.") == "O'Brien & Sons, Inc."


def test_validate_workspace_name_rejects_embedded_newline(db):
    """The name reaches an email *subject* line; a newline there is header
    injection. .strip() would not catch an interior one."""
    from app.core.errors import ConflictError
    from app.services.tenancy_service import validate_workspace_name

    with pytest.raises(ConflictError) as exc:
        validate_workspace_name("Acme\nBcc: victim@example.com")
    assert exc.value.code == "invalid_workspace_name"


def test_validate_workspace_name_rejects_tab_and_null(db):
    from app.core.errors import ConflictError
    from app.services.tenancy_service import validate_workspace_name

    for bad in ("Acme\tCorp", "Acme\x00Corp", "Acme\rCorp"):
        with pytest.raises(ConflictError):
            validate_workspace_name(bad)


def test_create_workspace_makes_owner_an_admin(db):
    owner = _user(db)
    workspace = TenancyService(db).create_workspace("Acme", owner)
    db.flush()
    memberships = TenancyService(db).list_memberships(owner.id)
    assert [m.workspace_id for m in memberships] == [workspace.id]
    assert memberships[0].role == WorkspaceRole.admin


def test_count_admins(db):
    owner = _user(db)
    workspace = TenancyService(db).create_workspace("Acme", owner)
    db.flush()
    assert TenancyService(db).count_admins(workspace.id) == 1
