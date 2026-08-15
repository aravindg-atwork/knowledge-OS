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


def _verified_signup(client, fake_email, workspace_name="Acme") -> tuple[str, str]:
    email = f"u-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "pw-pw-pw-pw",
            "full_name": "T",
            "workspace_name": workspace_name,
        },
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    return token, email


def test_me_reports_identity_and_workspaces(client, fake_email):
    token, email = _verified_signup(client, fake_email)
    body = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["email"] == email
    assert body["email_verified"] is True
    assert body["role"] == "admin"
    assert len(body["workspaces"]) == 1


def test_creating_a_second_workspace_shows_in_me(client, fake_email):
    token, _ = _verified_signup(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    second_name = f"Second-{uuid.uuid4().hex[:8]}"
    assert (
        client.post("/api/v1/workspaces", json={"name": second_name}, headers=headers).status_code
        == 201
    )
    body = client.get("/api/v1/auth/me", headers=headers).json()
    names = {w["name"] for w in body["workspaces"]}
    assert second_name in names
    assert len(body["workspaces"]) == 2


def test_switching_returns_a_token_scoped_to_the_new_workspace(client, fake_email):
    token, _ = _verified_signup(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    second = client.post(
        "/api/v1/workspaces", json={"name": f"Second-{uuid.uuid4().hex[:8]}"}, headers=headers
    ).json()

    switched = client.post(
        "/api/v1/auth/switch-workspace", json={"workspace_id": second["id"]}, headers=headers
    ).json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {switched}"}).json()
    assert me["active_workspace_id"] == second["id"]


def test_cannot_switch_into_a_workspace_you_do_not_belong_to(client, fake_email):
    token, _ = _verified_signup(client, fake_email)
    resp = client.post(
        "/api/v1/auth/switch-workspace",
        json={"workspace_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_switched_token_cannot_read_the_other_workspaces_documents(client, fake_email):
    """The load-bearing isolation test: switching must not leak across tenants."""
    token, _ = _verified_signup(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    second = client.post(
        "/api/v1/workspaces", json={"name": f"Second-{uuid.uuid4().hex[:8]}"}, headers=headers
    ).json()
    switched = client.post(
        "/api/v1/auth/switch-workspace", json={"workspace_id": second["id"]}, headers=headers
    ).json()["access_token"]

    docs = client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {switched}"}
    ).json()
    assert docs == []
