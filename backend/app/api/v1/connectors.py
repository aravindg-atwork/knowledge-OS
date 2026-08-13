from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models.sync_state import ConnectorAccount, ConnectorType
from app.workers.tasks_sync import sync_connector_task

router = APIRouter(prefix="/connectors", tags=["connectors"])


class SyncTriggerResponse(BaseModel):
    connector_account_id: str
    task_id: str


@router.post("/google-drive/sync", response_model=SyncTriggerResponse)
def trigger_google_drive_sync(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SyncTriggerResponse:
    account = db.scalars(
        select(ConnectorAccount).where(
            ConnectorAccount.workspace_id == current_user.workspace_id,
            ConnectorAccount.connector_type == ConnectorType.google_drive,
        )
    ).first()
    if account is None:
        raise NotFoundError("No Google Drive connector configured for this workspace")

    task = sync_connector_task.delay(str(account.id))
    return SyncTriggerResponse(connector_account_id=str(account.id), task_id=task.id)
