import re
import uuid

import pytest

from app.core.rate_limit import limiter
from app.email.factory import get_email_provider
from app.email.provider import FakeEmailProvider


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Rate limits are Redis-backed and keyed by client IP, which TestClient
    always reports as the same address. Without a reset, calls across this
    file's tests trip the limiter and return 429 instead of the status under
    test."""
    limiter.reset()
    yield


@pytest.fixture
def fake_email(client):
    """Override on the app instance `client` wraps. tests/conftest.py builds a
    fresh app per test via create_app(), so overriding app.main's module-level
    singleton would silently miss this client's requests."""
    provider = FakeEmailProvider()
    client.app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    client.app.dependency_overrides.pop(get_email_provider, None)


def _verified_admin(client, fake_email) -> tuple[str, str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "pw-pw-pw-pw", "full_name": "A", "workspace_name": "Acme"},
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    return token, email


def _invite_token(provider: FakeEmailProvider) -> str:
    return re.search(r"token=([A-Za-z0-9_\-]+)", provider.sent[-1].text).group(1)


def test_admin_can_invite_and_email_is_sent(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    invitee = f"new-{uuid.uuid4().hex[:8]}@acme.com"
    resp = client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert fake_email.sent[-1].to == invitee
    assert "Acme" in fake_email.sent[-1].text


def test_preview_reveals_workspace_without_auth(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    invitee = f"prev-{uuid.uuid4().hex[:8]}@acme.com"
    client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = client.get(
        f"/api/v1/invitations/preview?token={_invite_token(fake_email)}"
    ).json()
    assert body["workspace_name"] == "Acme"
    assert body["email"] == invitee
    # Preview must reveal only these two fields -- not the inviter or
    # anything else about the workspace.
    assert set(body.keys()) == {"workspace_name", "email"}


def test_new_user_accepting_an_invite_is_auto_verified(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    invitee = f"join-{uuid.uuid4().hex[:8]}@acme.com"
    client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    accepted = client.post(
        "/api/v1/invitations/accept",
        json={"token": _invite_token(fake_email), "password": "new-user-pw", "full_name": "N"},
    )
    assert accepted.status_code == 200
    new_token = accepted.json()["access_token"]
    # Auto-verified: receiving the invite proved they own the address.
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}).json()
    assert me["email_verified"] is True
    assert me["role"] == "member"


def test_logged_in_user_with_a_different_email_cannot_accept(client, fake_email):
    """Otherwise the membership would silently attach to the invited
    address's account rather than the person clicking the link."""
    admin_token, _ = _verified_admin(client, fake_email)
    other_token, _ = _verified_admin(client, fake_email)  # a different account
    invitee = f"someone-else-{uuid.uuid4().hex[:8]}@acme.com"
    client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = client.post(
        "/api/v1/invitations/accept",
        json={"token": _invite_token(fake_email)},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "invite_email_mismatch"


def test_malformed_bearer_token_on_accept_is_rejected_not_ignored(client, fake_email):
    """A present-but-undecodable session token must be a hard failure, not
    silently treated as "no session" -- otherwise a caller could bypass the
    email-mismatch guard just by sending garbage instead of a real token."""
    token, _ = _verified_admin(client, fake_email)
    invitee = f"broken-session-{uuid.uuid4().hex[:8]}@acme.com"
    client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.post(
        "/api/v1/invitations/accept",
        json={"token": _invite_token(fake_email)},
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "invalid_session"


def test_inviting_an_existing_member_conflicts(client, fake_email):
    token, admin_email = _verified_admin(client, fake_email)
    resp = client.post(
        "/api/v1/invitations",
        json={"email": admin_email, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "already_member"


def test_duplicate_pending_invite_conflicts(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    invitee = f"dup-{uuid.uuid4().hex[:8]}@acme.com"
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/invitations", json={"email": invitee, "role": "member"}, headers=headers)
    resp = client.post(
        "/api/v1/invitations", json={"email": invitee, "role": "member"}, headers=headers
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "invite_pending"


def test_revoked_invite_cannot_be_accepted(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    invitee = f"rev-{uuid.uuid4().hex[:8]}@acme.com"
    created = client.post(
        "/api/v1/invitations", json={"email": invitee, "role": "member"}, headers=headers
    ).json()
    raw = _invite_token(fake_email)
    assert client.delete(f"/api/v1/invitations/{created['id']}", headers=headers).status_code == 204
    resp = client.post(
        "/api/v1/invitations/accept",
        json={"token": raw, "password": "pw-pw-pw-pw", "full_name": "N"},
    )
    assert resp.status_code == 400


def test_member_cannot_invite(client, fake_email, db):
    from sqlalchemy import select

    from app.api.deps import invalidate_membership_cache
    from app.models.workspace import WorkspaceMembership, WorkspaceRole

    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    membership = db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == uuid.UUID(me["user_id"])
        )
    ).first()
    membership.role = WorkspaceRole.member
    db.commit()
    invalidate_membership_cache(
        uuid.UUID(me["user_id"]), uuid.UUID(me["active_workspace_id"])
    )
    resp = client.post(
        "/api/v1/invitations", json={"email": "x@acme.com", "role": "member"}, headers=headers
    )
    assert resp.status_code == 403


def test_concurrent_duplicate_invite_returns_409_not_500(db, monkeypatch):
    """Simulates the race between create()'s pending-invite SELECT and its
    later INSERT: another actor's invite for the same address has already
    landed by the time this call's pre-check ran (forced here by
    monkeypatching the pre-check to always report "no pending invite", as if
    it had raced and lost). The partial unique index on
    (workspace_id, email) WHERE accepted_at IS NULL must turn the resulting
    IntegrityError into the same clean ConflictError(code="invite_pending")
    the ordinary pre-check path raises -- never an unhandled 500.
    """
    from app.core.errors import ConflictError
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceRole
    from app.services.invitation_service import InvitationService

    suffix = uuid.uuid4().hex[:8]
    workspace = Workspace(name="Race Co", slug=f"race-co-{suffix}")
    db.add(workspace)
    admin = User(email=f"admin-{suffix}@race.local", hashed_password="x")
    db.add(admin)
    db.flush()

    email = f"race-{suffix}@race.local"
    service = InvitationService(db)

    # Force the pre-check to miss, as if it had raced and lost against a
    # concurrent invite for the same address that is about to land first.
    monkeypatch.setattr(InvitationService, "_pending_invite_exists", lambda self, *a: False)

    service.create(workspace.id, email, WorkspaceRole.member, admin.id)
    db.flush()

    with pytest.raises(ConflictError) as exc_info:
        service.create(workspace.id, email, WorkspaceRole.member, admin.id)
    assert exc_info.value.code == "invite_pending"
    assert exc_info.value.status_code == 409

    # The failed attempt's SAVEPOINT rollback must not have poisoned the
    # surrounding transaction -- the session must still be usable.
    db.flush()


def test_accept_invalidates_verification_cache_in_other_workspaces(client, fake_email, db):
    """FIX 2: InvitationService.accept() can flip email_verified_at on an
    existing, previously-unverified user. If that user already belongs to a
    *different* workspace whose membership cache was warmed while
    unverified, accepting the invite must invalidate that cache too -- not
    only the workspace being joined. No sleep should be required."""
    from app.core.security import create_access_token, hash_password
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

    admin_token, _ = _verified_admin(client, fake_email)

    suffix = uuid.uuid4().hex[:8]
    other_workspace = Workspace(name=f"Other {suffix}", slug=f"other-{suffix}")
    db.add(other_workspace)
    invitee_email = f"preexisting-{suffix}@acme.com"
    user = User(email=invitee_email, hashed_password=hash_password("x"))
    db.add(user)
    db.flush()
    db.add(
        WorkspaceMembership(
            workspace_id=other_workspace.id, user_id=user.id, role=WorkspaceRole.member
        )
    )
    db.commit()

    other_token = create_access_token(user.id, other_workspace.id)
    other_headers = {"Authorization": f"Bearer {other_token}"}

    # Warm the cache as unverified in the OTHER workspace.
    warm = client.get("/api/v1/auth/me", headers=other_headers)
    assert warm.status_code == 200
    assert warm.json()["email_verified"] is False

    client.post(
        "/api/v1/invitations",
        json={"email": invitee_email, "role": "member"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    accept_resp = client.post(
        "/api/v1/invitations/accept",
        json={"token": _invite_token(fake_email)},
        headers=other_headers,
    )
    assert accept_resp.status_code == 200

    # Immediately -- no sleep -- the OTHER workspace's verification-gated
    # endpoint must now succeed too.
    resp = client.get("/api/v1/documents", headers=other_headers)
    assert resp.status_code == 200


def test_preview_is_rate_limited(client, fake_email):
    """/preview is unauthenticated and consumes a secret token, so without a
    rate limit it would let any IP brute-force invite tokens at unlimited
    rate. RATE_LIMIT_INVITE_PREVIEW is 20/minute (see core/config.py) --
    exceed it within this single test and confirm the limiter is actually
    wired up, not just configured."""
    token, _ = _verified_admin(client, fake_email)
    invitee = f"ratelimit-{uuid.uuid4().hex[:8]}@acme.com"
    client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    raw = _invite_token(fake_email)

    statuses = [
        client.get(f"/api/v1/invitations/preview?token={raw}").status_code for _ in range(21)
    ]
    assert 429 in statuses
