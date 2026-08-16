import re
import uuid

import pytest

from app.core.rate_limit import limiter
from app.email.factory import get_email_provider
from app.email.provider import FakeEmailProvider


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """RATE_LIMIT_SIGNUP is Redis-backed (see app/core/rate_limit.py) and
    keyed by client IP, which TestClient always reports as the same address.
    Without a reset, signup/resend-verification calls across this file's
    tests would trip the limiter and fail with 429 instead of the status
    codes under test."""
    limiter.reset()
    yield


@pytest.fixture
def fake_email(client):
    """Overrides get_email_provider on the exact app instance `client` wraps.

    The `client` fixture (tests/conftest.py) builds a fresh app via
    create_app() per test rather than reusing the app.main module-level
    singleton, so dependency_overrides must be set on `client.app` -- setting
    them on `app.main.app` would silently miss this client's requests.
    """
    provider = FakeEmailProvider()
    client.app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    client.app.dependency_overrides.pop(get_email_provider, None)


def _link_token(provider: FakeEmailProvider) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", provider.sent[-1].text)
    assert match, f"no token in email: {provider.sent[-1].text}"
    return match.group(1)


def _signup_body(email: str) -> dict:
    # workspace_name is deliberately unique per call (not the literal "Acme
    # Corp"): this suite runs against the same Postgres DB as
    # test_tenancy_service.py, which asserts generate_slug("Acme Corp") ==
    # "acme-corp" -- a fixed name here would claim that slug and make that
    # unrelated test flaky/order-dependent.
    return {
        "email": email,
        "password": "correct-horse-battery",
        "full_name": "Test User",
        "workspace_name": f"Acme Corp {uuid.uuid4().hex[:8]}",
    }


def test_signup_creates_workspace_and_sends_verification(client, fake_email):
    email = f"new-{uuid.uuid4().hex[:8]}@acme.com"
    resp = client.post("/api/v1/auth/signup", json=_signup_body(email))
    assert resp.status_code == 201
    assert resp.json()["access_token"]
    assert len(fake_email.sent) == 1
    assert fake_email.sent[0].to == email


def test_duplicate_signup_is_rejected(client, fake_email):
    email = f"dup-{uuid.uuid4().hex[:8]}@acme.com"
    client.post("/api/v1/auth/signup", json=_signup_body(email))
    resp = client.post("/api/v1/auth/signup", json=_signup_body(email))
    assert resp.status_code == 409


def test_concurrent_signup_email_collision_returns_409_not_500(client, fake_email, monkeypatch):
    """get_user_by_email is a pre-check, not atomic with the User insert:
    a racing request that reads before the winner's commit is visible would
    sail past the pre-check and hit the DB's unique constraint on
    users.email instead. Simulate that race by forcing the pre-check to miss
    even though the row already exists, and assert the endpoint still
    returns a clean 409 (via the SAVEPOINT + IntegrityError handling around
    the insert) instead of an unhandled 500."""
    email = f"race-{uuid.uuid4().hex[:8]}@acme.com"
    first = client.post("/api/v1/auth/signup", json=_signup_body(email))
    assert first.status_code == 201

    from app.repositories.workspace_repository import WorkspaceRepository

    monkeypatch.setattr(WorkspaceRepository, "get_user_by_email", lambda self, email: None)

    resp = client.post("/api/v1/auth/signup", json=_signup_body(email))
    assert resp.status_code == 409
    assert resp.json()["code"] == "email_taken"


def test_unverified_user_is_blocked_from_documents(client, fake_email):
    email = f"unv-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post("/api/v1/auth/signup", json=_signup_body(email)).json()["access_token"]
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "email_not_verified"


def test_verification_unblocks_documents(client, fake_email):
    email = f"ver-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post("/api/v1/auth/signup", json=_signup_body(email)).json()["access_token"]
    assert client.post(
        "/api/v1/auth/verify-email", json={"token": _link_token(fake_email)}
    ).status_code == 200
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_verification_cache_invalidated_immediately_no_sleep(client, fake_email):
    """FIX 2: api/deps.py caches "role|verified" per (user, workspace) for
    60s. If verify-email doesn't invalidate that cache, a request made
    right after signup (e.g. the frontend's route-guard call to /auth/me)
    would warm the cache with verified=False, and a workspace-scoped
    endpoint would then keep 403ing with email_not_verified for up to 60s
    after verification actually succeeded -- even though the UI already
    thinks the user is in. This must not require any sleep to pass."""
    email = f"cache-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post("/api/v1/auth/signup", json=_signup_body(email)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Warm the membership cache in the unverified state, mirroring the
    # frontend's real route-guard call right after signup.
    warm = client.get("/api/v1/auth/me", headers=headers)
    assert warm.status_code == 200
    assert warm.json()["email_verified"] is False

    verify_resp = client.post(
        "/api/v1/auth/verify-email", json={"token": _link_token(fake_email)}
    )
    assert verify_resp.status_code == 200

    # Immediately -- no sleep, no waiting out the cache TTL.
    resp = client.get("/api/v1/documents", headers=headers)
    assert resp.status_code == 200


def test_verification_token_is_single_use(client, fake_email):
    email = f"once-{uuid.uuid4().hex[:8]}@acme.com"
    client.post("/api/v1/auth/signup", json=_signup_body(email))
    raw = _link_token(fake_email)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    resp = client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_token"


def test_garbage_verification_token_rejected(client, fake_email):
    resp = client.post("/api/v1/auth/verify-email", json={"token": "not-a-real-token"})
    assert resp.status_code == 400


def test_resend_verification_is_silent_for_unknown_email(client, fake_email):
    resp = client.post("/api/v1/auth/resend-verification", json={"email": "nobody@nowhere.com"})
    assert resp.status_code == 202
    assert fake_email.sent == []
