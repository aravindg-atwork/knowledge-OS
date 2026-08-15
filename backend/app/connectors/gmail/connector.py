from collections.abc import AsyncIterator
from typing import ClassVar

from app.connectors.base import Connector
from app.connectors.gmail.client import GmailClient
from app.connectors.google_drive.auth import MockOAuthTokenProvider, OAuthTokenProvider
from app.connectors.types import ChangeSet, ConnectorCredential, DownloadedFile, RemoteFile


class GmailConnector(Connector):
    """Contains zero mock-vs-real branching -- it only talks to `self._client`,
    whatever concrete implementation of GmailClient was injected. Mirrors
    GoogleDriveConnector's shape exactly."""

    connector_type: ClassVar[str] = "gmail"

    def __init__(
        self,
        client: GmailClient,
        token_provider: OAuthTokenProvider | None = None,
    ) -> None:
        self._client = client
        self._token_provider = token_provider or MockOAuthTokenProvider()

    async def authenticate(self, credential: ConnectorCredential) -> None:
        token = await self._token_provider.get_token(credential)
        self._client.set_token(token)

    async def discover(self) -> AsyncIterator[RemoteFile]:
        async for remote_file in self._client.list_files():
            yield remote_file

    async def detect_changes(self, cursor: str | None) -> ChangeSet:
        return await self._client.get_changes(cursor)

    async def download(self, file: RemoteFile) -> DownloadedFile:
        return await self._client.download_file(file.external_id)
