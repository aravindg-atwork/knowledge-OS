import re
import uuid

import pytest

from app.core.rate_limit import limiter
from app.email.factory import get_email_provider
from app.email.provider import FakeEmailProvider
from app.models.document import Document
from app.models.sync_state import ConnectorAccount, ConnectorMode, ConnectorType


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


def _create_document(db, workspace_id: uuid.UUID) -> uuid.UUID:
    """Mirrors the minimal ConnectorAccount+Document construction used by
    tests/integration/conftest.py's workspace_factory -- a real Document row
    needs a real ConnectorAccount FK, but this test only needs the document
    to exist and be workspace-scoped, not to go through a full sync."""
    suffix = uuid.uuid4().hex[:8]
    connector_account = ConnectorAccount(
        workspace_id=workspace_id,
        connector_type=ConnectorType.google_drive,
        mode=ConnectorMode.mock,
        display_name="Google Drive (Mock)",
    )
    db.add(connector_account)
    db.flush()

    document = Document(
        workspace_id=workspace_id,
        connector_account_id=connector_account.id,
        external_id=f"doc-{suffix}",
        title=f"Doc {suffix}",
        mime_type="text/plain",
        source_url=f"https://example.com/{suffix}",
    )
    db.add(document)
    db.commit()
    return document.id


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


def test_switched_token_cannot_read_the_other_workspaces_documents(client, fake_email, db):
    """The load-bearing isolation test: switching must not leak across tenants.

    A prior version of this test only asserted the empty second workspace
    returned `[]` from /documents -- vacuous, since that holds whether or not
    scoping works at all. This version puts a real document in workspace A,
    proves it is visible with a correctly-scoped token, then proves a token
    switched to workspace B cannot see it, and finally proves switching back
    makes it reappear (ruling out "the document was deleted" as an
    explanation for the earlier absence).
    """
    token, _ = _verified_signup(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}

    workspace_a_id = client.get("/api/v1/auth/me", headers=headers).json()["active_workspace_id"]
    document_id = str(_create_document(db, uuid.UUID(workspace_a_id)))

    # Sanity: the document is genuinely visible when correctly scoped, so a
    # later empty/absent result actually means something.
    docs_a = client.get("/api/v1/documents", headers=headers).json()
    assert {d["id"] for d in docs_a} == {document_id}

    second = client.post(
        "/api/v1/workspaces", json={"name": f"Second-{uuid.uuid4().hex[:8]}"}, headers=headers
    ).json()
    switched = client.post(
        "/api/v1/auth/switch-workspace", json={"workspace_id": second["id"]}, headers=headers
    ).json()["access_token"]

    docs_b = client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {switched}"}
    ).json()
    assert document_id not in {d["id"] for d in docs_b}
    assert docs_b == []

    # Switch back: the document reappears, confirming it was never deleted --
    # only out of scope for workspace B's token.
    switched_back = client.post(
        "/api/v1/auth/switch-workspace", json={"workspace_id": workspace_a_id}, headers=headers
    ).json()["access_token"]
    docs_a_again = client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {switched_back}"}
    ).json()
    assert {d["id"] for d in docs_a_again} == {document_id}
