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


def _signup(client, email: str) -> None:
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "original-password",
            "full_name": "T",
            "workspace_name": f"Acme-{uuid.uuid4().hex[:8]}",
        },
    )


def _link_token(provider: FakeEmailProvider) -> str:
    return re.search(r"token=([A-Za-z0-9_\-]+)", provider.sent[-1].text).group(1)


def test_forgot_password_returns_202_for_unknown_email(client, fake_email):
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@nowhere.com"})
    assert resp.status_code == 202
    assert fake_email.sent == []


def test_forgot_password_response_is_identical_for_known_and_unknown(client, fake_email):
    email = f"known-{uuid.uuid4().hex[:8]}@acme.com"
    _signup(client, email)
    known = client.post("/api/v1/auth/forgot-password", json={"email": email})
    unknown = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@nowhere.com"})
    assert known.status_code == unknown.status_code
    assert known.json() == unknown.json()


def test_reset_changes_the_password(client, fake_email):
    email = f"reset-{uuid.uuid4().hex[:8]}@acme.com"
    _signup(client, email)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    raw = _link_token(fake_email)

    assert client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": "brand-new-password"}
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": "brand-new-password"}
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": "original-password"}
    ).status_code == 401


def test_reset_token_is_single_use(client, fake_email):
    email = f"once-{uuid.uuid4().hex[:8]}@acme.com"
    _signup(client, email)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    raw = _link_token(fake_email)
    client.post("/api/v1/auth/reset-password", json={"token": raw, "new_password": "first-change"})
    resp = client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": "second-change"}
    )
    assert resp.status_code == 400


def test_verification_token_cannot_be_used_for_password_reset(client, fake_email):
    """Only tokens with purpose == password_reset are accepted -- a
    verification token issued by signup must not double as a reset token."""
    email = f"wrongpurpose-{uuid.uuid4().hex[:8]}@acme.com"
    _signup(client, email)
    verify_raw = _link_token(fake_email)

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": verify_raw, "new_password": "should-not-work"},
    )
    assert resp.status_code == 400
