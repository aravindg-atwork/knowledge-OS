from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers


def _client_with_boom_route(environment: str) -> TestClient:
    """A minimal app wired only with register_exception_handlers, so the
    test controls `environment` directly instead of depending on the
    process-wide cached Settings singleton."""
    app = FastAPI()
    register_exception_handlers(app, environment=environment)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("super secret internal detail")

    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_hides_detail_outside_dev():
    client = _client_with_boom_route("production")
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "super secret internal detail" not in response.text


def test_unhandled_exception_shows_detail_in_dev():
    client = _client_with_boom_route("dev")
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "super secret internal detail"}


def test_security_headers_present_on_every_response(client):
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == "default-src 'none'"
    # ENABLE_HSTS defaults to True
    assert "strict-transport-security" in response.headers
