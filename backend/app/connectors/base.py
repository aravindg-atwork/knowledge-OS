from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import ClassVar

from app.connectors.types import ChangeSet, ConnectorCredential, DownloadedFile, RemoteFile


class Connector(ABC):
    """Lifecycle contract every source-system integration implements.

    Concrete connectors (Google Drive, SharePoint, Zoho, ...) must not branch on
    "mock vs real" internally -- that boundary lives one level down, in the
    client object injected into the connector's constructor. The connector
    itself only ever talks to its client through the client's own protocol.
    """

    connector_type: ClassVar[str]

    @abstractmethod
    async def authenticate(self, credential: ConnectorCredential) -> None:
        """Establish/validate access before any discover/sync calls."""

    @abstractmethod
    async def discover(self) -> AsyncIterator[RemoteFile]:
        """Full listing of every file currently visible to this connector account."""

    @abstractmethod
    async def detect_changes(self, cursor: str | None) -> ChangeSet:
        """Incremental changes since `cursor` (None means "since the beginning")."""

    @abstractmethod
    async def download(self, file: RemoteFile) -> DownloadedFile:
        """Fetch raw bytes + mime type for a single file."""
