"""Shared real Google OAuth machinery, used by both the Drive and Gmail
connectors (same Google identity, different scopes).

Two separate concerns live here:

1. The browser consent flow (`build_authorization_url` / `exchange_code`) --
   invoked once from the API layer (see app/api/v1/connectors.py) when a user
   clicks "Connect Google Drive"/"Connect Gmail". This must happen in the
   user's own browser; nothing here can complete it on the server's behalf.
2. `GoogleOAuthTokenProvider`, the `OAuthTokenProvider` implementation
   Connector.authenticate() calls on every sync/download. It holds no
   long-lived state itself -- given a persisted `refresh_token` (stored in
   ConnectorAccount.credential_ref after step 1), it exchanges it for a
   fresh short-lived access token on every call. Google's token endpoint is
   cheap enough that re-exchanging per call is simpler and more robust than
   caching+expiry-tracking an access token across Celery task boundaries.
"""

import asyncio

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.connectors.google_drive.auth import OAuthTokenProvider
from app.connectors.types import ConnectorCredential

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def _client_config(client_id: str, client_secret: str, redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }


def build_authorization_url(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
) -> str:
    """Returns the Google consent-screen URL the user's browser must open."""
    flow = Flow.from_client_config(
        _client_config(client_id, client_secret, redirect_uri),
        scopes=scopes,
        redirect_uri=redirect_uri,
        state=state,
    )
    # access_type=offline + prompt=consent are both required to guarantee a
    # refresh_token comes back -- Google only issues one on the *first*
    # consent per client/user/scope combo unless prompt=consent forces it
    # again, which matters for reconnect flows.
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return auth_url


def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scopes: list[str],
    code: str,
) -> Credentials:
    """Exchanges the one-time `code` Google appended to the callback redirect
    for real tokens. Raises if Google didn't return a refresh_token (e.g. the
    user had already granted consent and Google silently skipped re-issuing
    one -- the caller should have forced prompt=consent to avoid this)."""
    flow = Flow.from_client_config(
        _client_config(client_id, client_secret, redirect_uri),
        scopes=scopes,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    credentials = flow.credentials
    if not credentials.refresh_token:
        raise ValueError(
            "Google did not return a refresh_token. Revoke this app's access at "
            "https://myaccount.google.com/permissions and try connecting again."
        )
    return credentials


class GoogleOAuthTokenProvider(OAuthTokenProvider):
    def __init__(self, client_id: str, client_secret: str) -> None:
        if not client_id or not client_secret:
            raise ValueError(
                "GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET must be set to use "
                "a real (non-mock) Google connector."
            )
        self._client_id = client_id
        self._client_secret = client_secret

    async def get_token(self, credential: ConnectorCredential) -> str:
        refresh_token = credential.extra.get("refresh_token")
        if not refresh_token:
            raise ValueError(
                f"Connector account {credential.connector_account_id} has no stored "
                "refresh_token -- it needs to complete the Google OAuth consent flow "
                "(GET /api/v1/connectors/google/oauth/start) before it can sync."
            )
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=self._client_id,
            client_secret=self._client_secret,
        )
        # google-auth's refresh() is a blocking requests call -- push it off
        # the event loop rather than stalling every other in-flight request.
        await asyncio.to_thread(credentials.refresh, Request())
        return credentials.token
