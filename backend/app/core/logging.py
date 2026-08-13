import json
import logging
import sys

from app.core.request_context import get_request_id

# Standard attributes every LogRecord carries -- anything else on the record
# (i.e. keys passed via `logger.info(msg, extra={...})`) is an
# application-supplied field and gets folded into the JSON payload.
_STANDARD_LOG_RECORD_ATTRS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__.keys()
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per log line, safe for log aggregators.

    Used outside local dev (see `configure_logging`) so structured fields
    (request id, audit event fields, etc.) survive as real JSON keys instead
    of being flattened into free text.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(environment: str = "dev", level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    if environment == "dev":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
