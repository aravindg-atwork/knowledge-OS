import logging

_audit_logger = logging.getLogger("audit")


def log_audit_event(event: str, **fields: object) -> None:
    """Emit a structured audit-trail log line for a permission-sensitive action.

    A log line, not a new DB table -- this codebase has one Alembic
    migration and no audit-trail precedent, so a log-based trail needs no
    migration/model/repository and rides directly on the JSON structured
    logger (`app.core.logging.JsonFormatter`) outside dev, making it
    immediately queryable by any downstream log aggregator. A DB-backed
    trail queryable from the app itself is a reasonable future upgrade, not
    needed for this milestone.

    `event` should be a stable, dotted name (e.g. "auth.login.success",
    "document.access.denied") so log queries can filter on it reliably.
    """
    _audit_logger.info(event, extra={"audit_event": event, **fields})
