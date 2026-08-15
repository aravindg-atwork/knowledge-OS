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


@pytest.mark.skip(reason="verified-email gate lands in Task 7 (app/api/deps.py)")
def test_unverified_user_is_blocked_from_documents(client, fake_email):
    email = f"unv-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post("/api/v1/auth/signup", json=_signup_body(email)).json()["access_token"]
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "email_not_verified"


@pytest.mark.skip(reason="verified-email gate lands in Task 7 (app/api/deps.py)")
def test_verification_unblocks_documents(client, fake_email):
    email = f"ver-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post("/api/v1/auth/signup", json=_signup_body(email)).json()["access_token"]
    assert client.post(
        "/api/v1/auth/verify-email", json={"token": _link_token(fake_email)}
    ).status_code == 200
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
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
