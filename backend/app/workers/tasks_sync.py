import uuid

from sqlalchemy import select

from app.core.errors import TransientConnectorError
from app.db.session import SessionLocal
from app.repositories.document_repository import DocumentRepository
from app.services.sync_service import SyncService
from app.workers.celery_app import celery_app
from app.workers.task_utils import CONNECTOR_RETRY_KWARGS, remote_file_to_dict


@celery_app.task(
    name="app.workers.tasks_sync.sync_connector_task",
    bind=True,
    autoretry_for=(TransientConnectorError,),
    **CONNECTOR_RETRY_KWARGS,
)
def sync_connector_task(self, connector_account_id: str) -> dict:
    db = SessionLocal()
    try:
        change_set = SyncService(db).run_sync(uuid.UUID(connector_account_id))

        document_repo = DocumentRepository(db)
        for external_id in change_set.deleted_ids:
            document = document_repo.find_by_external_id(
                uuid.UUID(connector_account_id), external_id
            )
            if document is not None:
                document_repo.mark_deleted(document)
        db.commit()
    finally:
        db.close()

    from app.workers.tasks_ingestion import process_document_task

    for remote_file in change_set.changed:
        process_document_task.delay(connector_account_id, remote_file_to_dict(remote_file))

    return {"changed": len(change_set.changed), "deleted": len(change_set.deleted_ids)}


@celery_app.task(name="app.workers.tasks_sync.sync_all_connectors_task")
def sync_all_connectors_task() -> dict:
    """Celery beat entry point: syncs every configured connector account.

    Defence in depth: TenancyService.remove_member deletes a removed
    member's ConnectorAccount rows as the primary fix, but this task is the
    backstop. It skips any user-owned account whose (workspace_id, user_id)
    no longer has a membership row -- covering any other path that could
    leave a connector account orphaned. Accounts with user_id IS NULL are
    the shared/workspace-level accounts (e.g. the mock seed connector) and
    have no owning membership to check, so they always sync.
    """
    from app.models.sync_state import ConnectorAccount
    from app.models.workspace import WorkspaceMembership

    db = SessionLocal()
    try:
        account_ids = []
        for account in db.scalars(select(ConnectorAccount)):
            if account.user_id is not None:
                membership = db.scalars(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == account.workspace_id,
                        WorkspaceMembership.user_id == account.user_id,
                    )
                ).first()
                if membership is None:
                    continue
            account_ids.append(str(account.id))
    finally:
        db.close()

    for account_id in account_ids:
        sync_connector_task.delay(account_id)

    return {"triggered": len(account_ids)}
