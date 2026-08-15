import asyncio
import uuid

from sqlalchemy.orm import Session

from app.connectors.base import Connector
from app.connectors.registry import get_connector
from app.connectors.types import ChangeSet, ConnectorCredential
from app.models.sync_state import ConnectorAccount, SyncRunStatus
from app.repositories.sync_repository import SyncRepository


class SyncService:
    """Runs discover() (first sync for an account) or detect_changes()
    (every subsequent sync) against whatever connector is registered for
    the account's (connector_type, mode), and records the sync_runs row.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._sync_repo = SyncRepository(db)

    def run_sync(self, connector_account_id: uuid.UUID) -> ChangeSet:
        account = self._sync_repo.get_connector_account(connector_account_id)
        if account is None:
            raise ValueError(f"No connector account {connector_account_id}")

        connector = get_connector(account.connector_type, account.mode)
        run = self._sync_repo.start_run(connector_account_id)
        cursor = self._sync_repo.get_cursor(connector_account_id)

        try:
            change_set = asyncio.run(self._fetch_changes(connector, account, cursor))
            self._sync_repo.set_cursor(connector_account_id, change_set.next_cursor)
            self._sync_repo.finish_run(
                run,
                status=SyncRunStatus.success,
                files_discovered=len(change_set.changed) + len(change_set.deleted_ids),
                files_changed=len(change_set.changed),
                files_failed=0,
            )
            return change_set
        except Exception as exc:
            self._sync_repo.finish_run(run, status=SyncRunStatus.failed, error_message=str(exc))
            raise

    @staticmethod
    async def _fetch_changes(
        connector: Connector, account: ConnectorAccount, cursor: str | None
    ) -> ChangeSet:
        await connector.authenticate(
            ConnectorCredential(connector_account_id=str(account.id), extra=account.credential_ref)
        )
        if cursor is None:
            # First sync for this account: the seed corpus is a baseline,
            # not a "change" -- next_cursor="0" so the next detect_changes
            # call only surfaces genuinely new edits.
            files = [f async for f in connector.discover()]
            return ChangeSet(changed=files, deleted_ids=[], next_cursor="0")
        return await connector.detect_changes(cursor)
