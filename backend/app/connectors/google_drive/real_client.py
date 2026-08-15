import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.connectors.types import ChangeSet, DownloadedFile, RemoteFile
from app.core.errors import TransientConnectorError
from app.pipeline.checksum import sha256_hex

# Native Google Workspace types (Docs/Sheets/Slides) have no downloadable
# bytes -- Drive must "export" them to a concrete format instead of
# files().get_media(). Exporting everything to a format the existing
# extractors (pipeline/extractors/) already understand avoids needing a new
# extractor per Workspace type.
_EXPORT_MIME_TYPES = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_LIST_FIELDS = (
    "nextPageToken, files(id,name,mimeType,modifiedTime,webViewLink,size,md5Checksum,"
    "lastModifyingUser)"
)


class RealGoogleDriveClient:
    """Implements the `GoogleDriveClient` protocol against Drive API v3.

    Stateless besides the current access token: `set_token()` is called by
    GoogleDriveConnector.authenticate() on every sync/download before any of
    the methods below run, so a fresh service object is always built from a
    live (just-refreshed) token rather than caching one that might expire
    mid-sync.
    """

    def __init__(self) -> None:
        self._access_token: str | None = None

    def set_token(self, access_token: str) -> None:
        self._access_token = access_token

    def _service(self):
        if not self._access_token:
            raise RuntimeError("RealGoogleDriveClient used before set_token() / authenticate()")
        credentials = Credentials(token=self._access_token)
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    async def list_files(self) -> AsyncIterator[RemoteFile]:
        for remote_file in await asyncio.to_thread(self._list_all_files):
            yield remote_file

    def _list_all_files(self) -> list[RemoteFile]:
        service = self._service()
        files: list[RemoteFile] = []
        page_token = None
        while True:
            try:
                response = (
                    service.files()
                    .list(
                        q="trashed = false and mimeType != 'application/vnd.google-apps.folder'",
                        pageSize=100,
                        fields=_LIST_FIELDS,
                        pageToken=page_token,
                    )
                    .execute()
                )
            except HttpError as exc:
                raise TransientConnectorError(str(exc)) from exc
            files.extend(_to_remote_file(f) for f in response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return files

    async def get_changes(self, page_token: str | None) -> ChangeSet:
        return await asyncio.to_thread(self._get_changes_sync, page_token)

    def _get_changes_sync(self, page_token: str | None) -> ChangeSet:
        service = self._service()
        try:
            if not page_token or page_token == "0":
                # Mirrors SyncService's convention: cursor "0" means "we just
                # ran discover(), nothing to reconcile yet" -- just mint a
                # real startPageToken for the *next* call to diff against.
                start = service.changes().getStartPageToken().execute()
                return ChangeSet(changed=[], deleted_ids=[], next_cursor=start["startPageToken"])

            changed: list[RemoteFile] = []
            deleted_ids: list[str] = []
            next_token = page_token
            while True:
                response = (
                    service.changes()
                    .list(
                        pageToken=next_token,
                        fields="nextPageToken,newStartPageToken,"
                        "changes(fileId,removed,file(id,name,mimeType,modifiedTime,"
                        "webViewLink,size,md5Checksum,lastModifyingUser))",
                    )
                    .execute()
                )
                for change in response.get("changes", []):
                    if change.get("removed") or not change.get("file"):
                        deleted_ids.append(change["fileId"])
                    else:
                        changed.append(_to_remote_file(change["file"]))
                if "newStartPageToken" in response:
                    return ChangeSet(
                        changed=changed,
                        deleted_ids=deleted_ids,
                        next_cursor=response["newStartPageToken"],
                    )
                next_token = response["nextPageToken"]
        except HttpError as exc:
            raise TransientConnectorError(str(exc)) from exc

    async def download_file(self, external_id: str) -> DownloadedFile:
        return await asyncio.to_thread(self._download_file_sync, external_id)

    def _download_file_sync(self, external_id: str) -> DownloadedFile:
        service = self._service()
        try:
            meta = service.files().get(fileId=external_id, fields="mimeType").execute()
            source_mime = meta["mimeType"]
            export_mime = _EXPORT_MIME_TYPES.get(source_mime)
            if export_mime:
                content = service.files().export(fileId=external_id, mimeType=export_mime).execute()
                mime_type = export_mime
            else:
                content = service.files().get_media(fileId=external_id).execute()
                mime_type = source_mime
        except HttpError as exc:
            raise TransientConnectorError(str(exc)) from exc
        return DownloadedFile(content=content, mime_type=mime_type, checksum=sha256_hex(content))


def _to_remote_file(f: dict) -> RemoteFile:
    return RemoteFile(
        external_id=f["id"],
        name=f.get("name", f["id"]),
        mime_type=f.get("mimeType", "application/octet-stream"),
        modified_time=(
            datetime.fromisoformat(f["modifiedTime"].replace("Z", "+00:00"))
            if f.get("modifiedTime")
            else datetime.now(UTC)
        ),
        source_url=f.get("webViewLink", f"https://drive.google.com/file/d/{f['id']}/view"),
        author=(f.get("lastModifyingUser") or {}).get("displayName"),
        size_bytes=int(f["size"]) if f.get("size") else 0,
        checksum_hint=f.get("md5Checksum"),
    )
