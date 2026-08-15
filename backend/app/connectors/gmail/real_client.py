import asyncio
import base64
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.connectors.types import ChangeSet, DownloadedFile, RemoteFile
from app.core.errors import TransientConnectorError
from app.pipeline.checksum import sha256_hex

_METADATA_HEADERS = ["Subject", "From", "Date"]
_LIST_QUERY = "-in:chats -in:spam -in:trash"


class RealGmailClient:
    """Implements the `GmailClient` protocol against Gmail API v1. Mirrors
    RealGoogleDriveClient: stateless besides the current access token,
    rebuilds the service object from `set_token()` on every call."""

    def __init__(self) -> None:
        self._access_token: str | None = None

    def set_token(self, access_token: str) -> None:
        self._access_token = access_token

    def _service(self):
        if not self._access_token:
            raise RuntimeError("RealGmailClient used before set_token() / authenticate()")
        credentials = Credentials(token=self._access_token)
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    async def list_files(self):
        for remote_file in await asyncio.to_thread(self._list_all_messages):
            yield remote_file

    def _list_all_messages(self) -> list[RemoteFile]:
        service = self._service()
        message_ids: list[str] = []
        page_token = None
        try:
            while True:
                response = (
                    service.users()
                    .messages()
                    .list(userId="me", q=_LIST_QUERY, maxResults=100, pageToken=page_token)
                    .execute()
                )
                message_ids.extend(m["id"] for m in response.get("messages", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            return [self._get_metadata(service, mid) for mid in message_ids]
        except HttpError as exc:
            raise TransientConnectorError(str(exc)) from exc

    async def get_changes(self, cursor: str | None) -> ChangeSet:
        return await asyncio.to_thread(self._get_changes_sync, cursor)

    def _get_changes_sync(self, cursor: str | None) -> ChangeSet:
        service = self._service()
        try:
            if not cursor or cursor == "0":
                # Mirrors the Drive client's startPageToken convention: we
                # just ran discover(), nothing to reconcile yet -- mint a
                # historyId baseline for the *next* call to diff against.
                profile = service.users().getProfile(userId="me").execute()
                return ChangeSet(changed=[], deleted_ids=[], next_cursor=str(profile["historyId"]))

            added_ids: dict[str, None] = {}  # ordered dedupe
            deleted_ids: dict[str, None] = {}
            next_cursor = cursor
            page_token = None
            while True:
                try:
                    response = (
                        service.users()
                        .history()
                        .list(
                            userId="me",
                            startHistoryId=cursor,
                            historyTypes=["messageAdded", "messageDeleted"],
                            pageToken=page_token,
                        )
                        .execute()
                    )
                except HttpError as exc:
                    if exc.resp.status == 404:
                        raise TransientConnectorError(
                            "Gmail historyId expired (mailbox history retention is ~30 days) "
                            "-- this connector account needs a fresh full sync."
                        ) from exc
                    raise
                for record in response.get("history", []):
                    for added in record.get("messagesAdded", []):
                        mid = added["message"]["id"]
                        added_ids[mid] = None
                        deleted_ids.pop(mid, None)
                    for removed in record.get("messagesDeleted", []):
                        mid = removed["message"]["id"]
                        deleted_ids[mid] = None
                        added_ids.pop(mid, None)
                if "historyId" in response:
                    next_cursor = str(response["historyId"])
                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            changed = [self._get_metadata(service, mid) for mid in added_ids]
            return ChangeSet(
                changed=changed, deleted_ids=list(deleted_ids), next_cursor=next_cursor
            )
        except HttpError as exc:
            raise TransientConnectorError(str(exc)) from exc

    def _get_metadata(self, service, message_id: str) -> RemoteFile:
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata", metadataHeaders=_METADATA_HEADERS)
            .execute()
        )
        headers = {h["name"]: h["value"] for h in message.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "(no subject)")
        sender = headers.get("From")
        date = _parse_date(headers.get("Date"))
        return RemoteFile(
            external_id=message_id,
            name=subject,
            mime_type="text/plain",
            modified_time=date,
            source_url=f"https://mail.google.com/mail/u/0/#all/{message_id}",
            author=sender,
            size_bytes=message.get("sizeEstimate", 0),
            checksum_hint=None,
        )

    async def download_file(self, external_id: str) -> DownloadedFile:
        return await asyncio.to_thread(self._download_message_sync, external_id)

    def _download_message_sync(self, external_id: str) -> DownloadedFile:
        service = self._service()
        try:
            message = (
                service.users()
                .messages()
                .get(userId="me", id=external_id, format="full")
                .execute()
            )
        except HttpError as exc:
            raise TransientConnectorError(str(exc)) from exc

        payload = message.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
        body_text = _extract_plain_text(payload)
        full_text = (
            f"Subject: {headers.get('Subject', '')}\n"
            f"From: {headers.get('From', '')}\n"
            f"To: {headers.get('To', '')}\n\n"
            f"{body_text}"
        )
        content = full_text.encode("utf-8")
        return DownloadedFile(content=content, mime_type="text/plain", checksum=sha256_hex(content))


def _parse_date(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _decode_body(data: str) -> str:
    # Gmail base64url-encodes body data, sometimes without padding.
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_plain_text(payload: dict) -> str:
    """Walks a Gmail message payload (which may be a single part or a nested
    multipart tree) and returns the best plain-text representation: prefers a
    text/plain part, falls back to stripping tags from text/html."""
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict) -> None:
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data and mime_type == "text/plain":
            plain_parts.append(_decode_body(data))
        elif data and mime_type == "text/html":
            html_parts.append(_decode_body(data))
        for sub_part in part.get("parts", []) or []:
            walk(sub_part)

    walk(payload)

    if plain_parts:
        return "\n\n".join(plain_parts)
    if html_parts:
        return "\n\n".join(BeautifulSoup(html, "html.parser").get_text() for html in html_parts)
    return ""
