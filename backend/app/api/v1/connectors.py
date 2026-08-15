import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.connectors import google_oauth
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.security import create_oauth_state_token, decode_oauth_state_token
from app.db.session import get_db
from app.models.sync_state import ConnectorAccount, ConnectorMode, ConnectorType
from app.models.user import User
from app.workers.tasks_sync import sync_connector_task

router = APIRouter(prefix="/connectors", tags=["connectors"])

_SCOPES_BY_TYPE = {
    ConnectorType.google_drive: [google_oauth.DRIVE_READONLY_SCOPE],
    ConnectorType.gmail: [google_oauth.GMAIL_READONLY_SCOPE],
}
_DISPLAY_NAME_BY_TYPE = {
    ConnectorType.google_drive: "Google Drive",
    ConnectorType.gmail: "Gmail",
}


class SyncTriggerResponse(BaseModel):
    connector_account_id: str
    task_id: str


def _trigger_sync(
    connector_type: ConnectorType, current_user: CurrentUser, db: Session
) -> SyncTriggerResponse:
    # Scoped to the caller's own connection -- a workspace can have several
    # (one per teammate who connected), so "sync now" means "sync mine", not
    # "sync whichever one happens to match this workspace+type".
    account = db.scalars(
        select(ConnectorAccount).where(
            ConnectorAccount.workspace_id == current_user.workspace_id,
            ConnectorAccount.connector_type == connector_type,
            ConnectorAccount.user_id == current_user.user_id,
        )
    ).first()
    if account is None:
        raise NotFoundError(
            f"You haven't connected {_DISPLAY_NAME_BY_TYPE[connector_type]} yet -- "
            "connect it first via /connectors/google/oauth/start"
        )
    task = sync_connector_task.delay(str(account.id))
    return SyncTriggerResponse(connector_account_id=str(account.id), task_id=task.id)


@router.post("/google-drive/sync", response_model=SyncTriggerResponse)
def trigger_google_drive_sync(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SyncTriggerResponse:
    return _trigger_sync(ConnectorType.google_drive, current_user, db)


@router.post("/gmail/sync", response_model=SyncTriggerResponse)
def trigger_gmail_sync(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SyncTriggerResponse:
    return _trigger_sync(ConnectorType.gmail, current_user, db)


class OAuthStartResponse(BaseModel):
    authorization_url: str


@router.get("/google/oauth/start", response_model=OAuthStartResponse)
def start_google_oauth(
    connector_type: ConnectorType = Query(..., description="google_drive or gmail"),
    current_user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> OAuthStartResponse:
    """Called by the frontend (authenticated fetch) to get the Google consent
    URL; the frontend then navigates the browser there itself
    (window.location = authorization_url) -- this endpoint can't redirect the
    browser directly because it needs the caller's Bearer token, which a
    plain top-level navigation wouldn't send."""
    if connector_type not in _SCOPES_BY_TYPE:
        raise NotFoundError(f"No Google OAuth flow for connector_type={connector_type}")

    state = create_oauth_state_token(
        current_user.workspace_id, current_user.user_id, connector_type.value
    )
    url = google_oauth.build_authorization_url(
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
        scopes=_SCOPES_BY_TYPE[connector_type],
        state=state,
    )
    return OAuthStartResponse(authorization_url=url)


@router.get("/google/oauth/callback", response_class=HTMLResponse)
def google_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> str:
    """Google redirects the user's browser here after they approve/deny
    consent. No Authorization header is available on this request -- `state`
    (minted by /oauth/start, verified here) is what ties this callback back
    to a workspace + teammate + connector_type."""
    if error:
        return _result_page(f"Google sign-in was cancelled or denied ({error}).", ok=False)
    if not code or not state:
        return _result_page("Missing code/state on Google OAuth callback.", ok=False)

    try:
        claims = decode_oauth_state_token(state)
    except Exception:
        return _result_page(
            "This connection link expired or is invalid. Please try again.", ok=False
        )

    connector_type = ConnectorType(claims["connector_type"])
    workspace_id = uuid.UUID(claims["workspace_id"])
    user_id = uuid.UUID(claims["user_id"])

    try:
        credentials = google_oauth.exchange_code(
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
            scopes=_SCOPES_BY_TYPE[connector_type],
            code=code,
        )
    except Exception as exc:
        return _result_page(f"Couldn't complete the Google connection: {exc}", ok=False)

    # One row per (workspace, connector_type, user) -- each teammate who
    # connects gets their own account, all pooling into the same
    # workspace-scoped corpus. Re-running consent for an account that
    # already exists (e.g. re-approving after a scope change) just refreshes
    # its stored token in place rather than creating a duplicate.
    account = db.scalars(
        select(ConnectorAccount).where(
            ConnectorAccount.workspace_id == workspace_id,
            ConnectorAccount.connector_type == connector_type,
            ConnectorAccount.user_id == user_id,
        )
    ).first()
    if account is None:
        user = db.get(User, user_id)
        owner_label = user.email if user else str(user_id)
        account = ConnectorAccount(
            workspace_id=workspace_id,
            connector_type=connector_type,
            user_id=user_id,
            display_name=f"{_DISPLAY_NAME_BY_TYPE[connector_type]} ({owner_label})",
        )
        db.add(account)
    account.mode = ConnectorMode.real
    account.credential_ref = {"refresh_token": credentials.refresh_token}
    db.commit()
    db.refresh(account)

    # Kick off an initial sync immediately so the workspace starts seeing
    # this teammate's content without a separate manual "sync now" click.
    sync_connector_task.delay(str(account.id))

    return _result_page(
        f"{_DISPLAY_NAME_BY_TYPE[connector_type]} connected. Syncing now -- you can close this tab."
    )


def _result_page(message: str, *, ok: bool = True) -> str:
    color = "#1a7f37" if ok else "#c62828"
    return (
        "<html><body style='font-family: system-ui; text-align: center; padding: 4rem;'>"
        f"<h2 style='color: {color}'>{message}</h2></body></html>"
    )
