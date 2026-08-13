from collections.abc import AsyncIterator

from app.connectors.types import ChangeSet, DownloadedFile, RemoteFile


class RealGoogleDriveClient:
    """Interface-matching placeholder for the real Google Drive API v3 client.

    Implements the same `GoogleDriveClient` protocol as `MockGoogleDriveClient`
    so `GoogleDriveConnector` can be pointed at either without modification.
    Not usable until real OAuth credentials exist -- every method raises until
    then. When implemented, this will wrap `googleapiclient.discovery.build(
    "drive", "v3", credentials=...)`, using `files().list()` for discover(),
    `changes().list(pageToken=...)` for detect_changes() (mirroring the mock's
    revision-cursor semantics), and `files().get_media()` for download().
    """

    async def list_files(self) -> AsyncIterator[RemoteFile]:
        raise NotImplementedError("Real Google Drive connector requires OAuth credentials")
        yield  # pragma: no cover -- makes this an async generator

    async def get_changes(self, page_token: str | None) -> ChangeSet:
        raise NotImplementedError("Real Google Drive connector requires OAuth credentials")

    async def download_file(self, external_id: str) -> DownloadedFile:
        raise NotImplementedError("Real Google Drive connector requires OAuth credentials")
