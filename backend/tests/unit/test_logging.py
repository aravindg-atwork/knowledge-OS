import json
import logging

from app.core.logging import JsonFormatter
from app.core.request_context import set_request_id


def test_health_response_carries_request_id_header(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_incoming_request_id_is_echoed_back(client):
    response = client.get("/health", headers={"X-Request-ID": "fixed-id"})
    assert response.headers["X-Request-ID"] == "fixed-id"


def test_json_formatter_emits_valid_json_with_request_id_and_extra_fields():
    set_request_id("abc-123")
    record = logging.LogRecord(
        name="app.request",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.http_status = 200

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.request"
    assert payload["request_id"] == "abc-123"
    assert payload["http_status"] == 200
