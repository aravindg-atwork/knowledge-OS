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


def test_a_usable_account_can_be_created_without_the_seed(client, fake_email):
    """The seed script is gone; signup must be sufficient to reach the app."""
    email = f"fresh-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "pw-pw-pw-pw",
            "full_name": "Fresh User",
            "workspace_name": f"Fresh Co {uuid.uuid4().hex[:8]}",
        },
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})

    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/documents", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "admin"
