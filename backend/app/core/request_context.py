"""Per-request correlation id, readable from anywhere in the call stack.

A `ContextVar` (not a thread-local) because Starlette/FastAPI run request
handling on asyncio -- a single OS thread interleaves many in-flight
requests across await points, so a thread-local would leak one request's id
into another's log lines.
"""

from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)
