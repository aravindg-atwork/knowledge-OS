import uuid

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.sync_state import ConnectorAccount, SyncCursor, SyncRun, SyncRunStatus


class SyncRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_connector_account(self, connector_account_id: uuid.UUID) -> ConnectorAccount | None:
        return self._db.get(ConnectorAccount, connector_account_id)

    def get_cursor(self, connector_account_id: uuid.UUID) -> str | None:
        cursor = self._db.get(SyncCursor, connector_account_id)
        return cursor.cursor_token if cursor else None

    def set_cursor(self, connector_account_id: uuid.UUID, cursor_token: str) -> None:
        cursor = self._db.get(SyncCursor, connector_account_id)
        if cursor is None:
            cursor = SyncCursor(
                connector_account_id=connector_account_id, cursor_token=cursor_token
            )
            self._db.add(cursor)
        else:
            cursor.cursor_token = cursor_token
            cursor.updated_at = utcnow()
        self._db.flush()

    def start_run(self, connector_account_id: uuid.UUID) -> SyncRun:
        run = SyncRun(
            connector_account_id=connector_account_id,
            started_at=utcnow(),
            status=SyncRunStatus.running,
        )
        self._db.add(run)
        self._db.flush()
        return run

    def finish_run(
        self,
        run: SyncRun,
        *,
        status: SyncRunStatus,
        files_discovered: int = 0,
        files_changed: int = 0,
        files_failed: int = 0,
        error_message: str | None = None,
    ) -> None:
        run.status = status
        run.finished_at = utcnow()
        run.files_discovered = files_discovered
        run.files_changed = files_changed
        run.files_failed = files_failed
        run.error_message = error_message
        self._db.flush()
