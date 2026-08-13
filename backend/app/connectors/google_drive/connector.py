from collections.abc import AsyncIterator
from typing import ClassVar

from app.connectors.base import Connector
from app.connectors.google_drive.auth import MockOAuthTokenProvider, OAuthTokenProvider
from app.connectors.google_drive.client import GoogleDriveClient
from app.connectors.types import ChangeSet, ConnectorCredential, DownloadedFile, RemoteFile


class GoogleDriveConnector(Connector):
    """Contains zero mock-vs-real branching -- it only talks to `self._client`,
    whatever concrete implementation of GoogleDriveClient was injected."""

    connector_type: ClassVar[str] = "google_drive"

    def __init__(
        self,
        client: GoogleDriveClient,
        token_provider: OAuthTokenProvider | None = None,
    ) -> None:
        self._client = client
        self._token_provider = token_provider or MockOAuthTokenProvider()

    async def authenticate(self, credential: ConnectorCredential) -> None:
        await self._token_provider.get_token(credential)

    async def discover(self) -> AsyncIterator[RemoteFile]:
        async for remote_file in self._client.list_files():
            yield remote_file

    async def detect_changes(self, cursor: str | None) -> ChangeSet:
        return await self._client.get_changes(cursor)

    async def download(self, file: RemoteFile) -> DownloadedFile:
        return await self._client.download_file(file.external_id)
