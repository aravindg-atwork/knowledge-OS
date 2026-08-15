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


def test_admin_sees_the_member_list(client, fake_email):
    token, email = _verified_admin(client, fake_email)
    body = client.get(
        "/api/v1/workspaces/current/members", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert [m["email"] for m in body] == [email]
    assert body[0]["role"] == "admin"


def test_cannot_demote_the_last_admin(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    resp = client.patch(
        f"/api/v1/workspaces/current/members/{me['user_id']}",
        json={"role": "member"},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "last_admin"


def test_cannot_remove_the_last_admin(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    resp = client.delete(
        f"/api/v1/workspaces/current/members/{me['user_id']}", headers=headers
    )
    assert resp.status_code == 409


def test_member_cannot_reach_admin_endpoints(client, fake_email, db):
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

    resp = client.get("/api/v1/workspaces/current/members", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == "admin_required"


def test_admin_can_change_a_members_role(client, fake_email, db):
    """Two admins in a workspace: demoting one leaves the other, so it must
    succeed (unlike the last-admin cases above)."""
    from sqlalchemy import select

    from app.api.deps import invalidate_membership_cache
    from app.models.workspace import WorkspaceMembership, WorkspaceRole

    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()

    other_email = f"admin2-{uuid.uuid4().hex[:8]}@acme.com"
    other_token = client.post(
        "/api/v1/auth/signup",
        json={
            "email": other_email,
            "password": "pw-pw-pw-pw",
            "full_name": "B",
            "workspace_name": f"Other {uuid.uuid4().hex[:8]}",
        },
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    other_me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {other_token}"}
    ).json()

    # Manually attach the second user to the first workspace as an admin so
    # the workspace has two admins, without needing the invitation flow.
    db.add(
        WorkspaceMembership(
            workspace_id=uuid.UUID(me["active_workspace_id"]),
            user_id=uuid.UUID(other_me["user_id"]),
            role=WorkspaceRole.admin,
        )
    )
    db.commit()
    invalidate_membership_cache(
        uuid.UUID(other_me["user_id"]), uuid.UUID(me["active_workspace_id"])
    )

    resp = client.patch(
        f"/api/v1/workspaces/current/members/{me['user_id']}",
        json={"role": "member"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "member"

    membership = db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == uuid.UUID(me["active_workspace_id"]),
            WorkspaceMembership.user_id == uuid.UUID(me["user_id"]),
        )
    ).first()
    assert membership.role == WorkspaceRole.member


def test_role_change_revocation_is_immediate_not_ttl_delayed(client, fake_email, db):
    """Proves invalidate_membership_cache is actually wired in: without it,
    a demoted admin would keep admin-level cached access for up to 60s."""
    from sqlalchemy import select

    from app.models.workspace import WorkspaceMembership, WorkspaceRole

    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()

    other_email = f"admin2-{uuid.uuid4().hex[:8]}@acme.com"
    other_token = client.post(
        "/api/v1/auth/signup",
        json={
            "email": other_email,
            "password": "pw-pw-pw-pw",
            "full_name": "B",
            "workspace_name": f"Other {uuid.uuid4().hex[:8]}",
        },
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    other_me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {other_token}"}
    ).json()
    other_user_id = uuid.UUID(other_me["user_id"])
    workspace_id = uuid.UUID(me["active_workspace_id"])

    db.add(
        WorkspaceMembership(
            workspace_id=workspace_id, user_id=other_user_id, role=WorkspaceRole.admin
        )
    )
    db.commit()

    from app.api.deps import invalidate_membership_cache

    invalidate_membership_cache(other_user_id, workspace_id)

    # A fresh token scoped to the *original* workspace for the second admin,
    # so their cached-role entry, once populated, lives under this exact
    # (user_id, workspace_id) cache key.
    from app.core.security import create_access_token

    other_workspace_token = create_access_token(other_user_id, workspace_id)
    other_headers = {"Authorization": f"Bearer {other_workspace_token}"}

    # Populate the cache with "admin" by making one authenticated call.
    warm_resp = client.get("/api/v1/workspaces/current/members", headers=other_headers)
    assert warm_resp.status_code == 200

    # The original admin demotes the second admin.
    demote_resp = client.patch(
        f"/api/v1/workspaces/current/members/{other_user_id}",
        json={"role": "member"},
        headers=headers,
    )
    assert demote_resp.status_code == 200

    # Immediately -- not after any sleep/TTL wait -- the demoted user must be
    # refused admin access. If invalidate_membership_cache were not called,
    # this would still return 200 for up to 60 seconds.
    resp = client.get("/api/v1/workspaces/current/members", headers=other_headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == "admin_required"


def test_admin_can_remove_a_member(client, fake_email, db):
    from sqlalchemy import select

    from app.models.workspace import WorkspaceMembership, WorkspaceRole

    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    workspace_id = uuid.UUID(me["active_workspace_id"])

    other_email = f"member2-{uuid.uuid4().hex[:8]}@acme.com"
    other_token = client.post(
        "/api/v1/auth/signup",
        json={
            "email": other_email,
            "password": "pw-pw-pw-pw",
            "full_name": "C",
            "workspace_name": f"Other {uuid.uuid4().hex[:8]}",
        },
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    other_me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {other_token}"}
    ).json()
    other_user_id = uuid.UUID(other_me["user_id"])

    db.add(
        WorkspaceMembership(
            workspace_id=workspace_id, user_id=other_user_id, role=WorkspaceRole.member
        )
    )
    db.commit()

    resp = client.delete(
        f"/api/v1/workspaces/current/members/{other_user_id}", headers=headers
    )
    assert resp.status_code == 204

    membership = db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == other_user_id,
        )
    ).first()
    assert membership is None


def test_rename_workspace(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    new_name = f"Renamed {uuid.uuid4().hex[:8]}"
    resp = client.patch(
        "/api/v1/workspaces/current", json={"name": new_name}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == new_name


@pytest.mark.parametrize(
    "bad_name",
    ["", "x" * 200, "bad<name>", "line1\nline2"],
)
def test_rename_workspace_rejects_what_signup_rejects(client, fake_email, bad_name):
    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.patch(
        "/api/v1/workspaces/current", json={"name": bad_name}, headers=headers
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "invalid_workspace_name"


def test_member_cannot_rename_workspace(client, fake_email, db):
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

    resp = client.patch(
        "/api/v1/workspaces/current", json={"name": "New Name"}, headers=headers
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "admin_required"
