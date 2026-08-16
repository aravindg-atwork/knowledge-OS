import uuid

import pytest

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceRole
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


def test_create_workspace_retries_past_slug_collision(db, monkeypatch):
    """Simulates the race between generate_slug's SELECT and the later
    INSERT: another actor has already taken the slug generate_slug would
    otherwise hand out first. create_workspace must retry with a fresh slug
    and succeed rather than raising an unhandled IntegrityError."""
    owner = _user(db)

    colliding = Workspace(name="Race Co", slug="race-co")
    db.add(colliding)
    db.flush()

    service = TenancyService(db)
    real_generate_slug = service.generate_slug
    calls = {"n": 0}

    def fake_generate_slug(name: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            # Force the first attempt onto the already-taken slug, as if
            # generate_slug's own uniqueness check had raced and lost.
            return "race-co"
        return real_generate_slug(name)

    monkeypatch.setattr(service, "generate_slug", fake_generate_slug)

    workspace = service.create_workspace("Race Co", owner)
    db.flush()

    assert calls["n"] >= 2
    assert workspace.slug != "race-co"
    assert workspace.id is not None


def test_create_workspace_retry_preserves_admin_membership(db, monkeypatch):
    owner = _user(db)

    colliding = Workspace(name="Race Co", slug="race-co")
    db.add(colliding)
    db.flush()

    service = TenancyService(db)
    real_generate_slug = service.generate_slug
    calls = {"n": 0}

    def fake_generate_slug(name: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "race-co"
        return real_generate_slug(name)

    monkeypatch.setattr(service, "generate_slug", fake_generate_slug)

    workspace = service.create_workspace("Race Co", owner)
    db.flush()

    memberships = service.list_memberships(owner.id)
    assert [m.workspace_id for m in memberships] == [workspace.id]
    assert memberships[0].role == WorkspaceRole.admin


def test_create_workspace_retry_does_not_poison_surrounding_transaction(db, monkeypatch):
    """A failed slug-collision attempt must roll back only its own
    SAVEPOINT, not the outer transaction -- create_workspace runs mid-request
    alongside other pending inserts (e.g. signup's User + AuthToken) that
    must survive a retry."""
    owner = _user(db)

    # Entity added to the session before the racy create_workspace call --
    # this stands in for other work already pending in the same transaction.
    bystander = User(email=f"bystander-{uuid.uuid4().hex[:8]}@t.local", hashed_password="x")
    db.add(bystander)

    colliding = Workspace(name="Race Co", slug="race-co")
    db.add(colliding)
    db.flush()

    service = TenancyService(db)
    real_generate_slug = service.generate_slug
    calls = {"n": 0}

    def fake_generate_slug(name: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "race-co"
        return real_generate_slug(name)

    monkeypatch.setattr(service, "generate_slug", fake_generate_slug)

    service.create_workspace("Race Co", owner)

    # The pre-existing pending entity must still be present and flushable --
    # a plain (non-savepoint) rollback during the retry would have discarded it.
    db.flush()
    assert bystander.id is not None
    assert db.get(User, bystander.id) is not None


def test_create_workspace_raises_clean_error_when_slugs_exhausted(db, monkeypatch):
    """If every attempt collides, create_workspace must raise a clean
    ConflictError -- never let an IntegrityError escape as an unhandled 500."""
    from app.core.errors import ConflictError

    owner = _user(db)
    service = TenancyService(db)

    monkeypatch.setattr(service, "generate_slug", lambda name: "always-taken")

    colliding = Workspace(name="Always Taken", slug="always-taken")
    db.add(colliding)
    db.flush()

    with pytest.raises(ConflictError) as exc:
        service.create_workspace("Always Taken", owner)
    assert exc.value.code == "slug_allocation_failed"
