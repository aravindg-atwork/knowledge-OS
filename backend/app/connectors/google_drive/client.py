from collections.abc import AsyncIterator
from typing import Protocol

from app.connectors.types import ChangeSet, DownloadedFile, RemoteFile


class GoogleDriveClient(Protocol):
    """The actual mock/real swap boundary.

    GoogleDriveConnector depends only on this protocol. MockGoogleDriveClient
    implements it against a fixture corpus; a future RealGoogleDriveClient
    implements it against `googleapiclient.discovery.build('drive', 'v3')`.
    Neither GoogleDriveConnector nor anything upstream of it (pipeline, API)
    needs to change when one is swapped for the other.
    """

    async def list_files(self) -> AsyncIterator[RemoteFile]: ...

    async def get_changes(self, page_token: str | None) -> ChangeSet: ...

    async def download_file(self, external_id: str) -> DownloadedFile: ...

    def set_token(self, access_token: str) -> None:
        """Called by GoogleDriveConnector.authenticate() with a fresh bearer
        token before any of the above run. Mock implementations ignore it."""
        ...
