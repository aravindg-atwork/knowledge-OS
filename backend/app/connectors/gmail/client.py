from collections.abc import AsyncIterator
from typing import Protocol

from app.connectors.types import ChangeSet, DownloadedFile, RemoteFile


class GmailClient(Protocol):
    """The mock/real swap boundary for Gmail, mirroring
    app.connectors.google_drive.client.GoogleDriveClient. GmailConnector
    depends only on this protocol -- MockGmailClient implements it against a
    fixture corpus, RealGmailClient against
    `googleapiclient.discovery.build('gmail', 'v1')`.

    A "file" here is one email message: list_files()/get_changes() return
    metadata only (subject/from/date), download_file() fetches and flattens
    the message body to plain text.
    """

    async def list_files(self) -> AsyncIterator[RemoteFile]: ...

    async def get_changes(self, cursor: str | None) -> ChangeSet: ...

    async def download_file(self, external_id: str) -> DownloadedFile: ...

    def set_token(self, access_token: str) -> None:
        """Called by GmailConnector.authenticate() with a fresh bearer token
        before any of the above run. Mock implementations ignore it."""
        ...
