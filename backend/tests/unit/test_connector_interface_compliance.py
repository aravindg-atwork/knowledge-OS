import inspect

import pytest

from app.connectors.base import Connector
from app.connectors.google_drive.connector import GoogleDriveConnector
from app.connectors.google_drive.mock_client import MockGoogleDriveClient
from app.connectors.types import ChangeSet, ConnectorCredential, DownloadedFile, RemoteFile


@pytest.fixture
def connector(tmp_path) -> GoogleDriveConnector:
    client = MockGoogleDriveClient(state_path=tmp_path / "state.json")
    return GoogleDriveConnector(client)


def test_google_drive_connector_is_a_connector(connector):
    assert isinstance(connector, Connector)


def test_all_abstract_methods_implemented():
    abstract_methods = {
        name
        for name, member in inspect.getmembers(Connector)
        if getattr(member, "__isabstractmethod__", False)
    }
    assert abstract_methods == {"authenticate", "discover", "detect_changes", "download"}
    for name in abstract_methods:
        assert hasattr(GoogleDriveConnector, name)


async def test_authenticate_does_not_raise(connector):
    await connector.authenticate(ConnectorCredential(connector_account_id="acct-1"))


async def test_discover_yields_remote_files(connector):
    files = [f async for f in connector.discover()]
    assert len(files) == 10
    assert all(isinstance(f, RemoteFile) for f in files)


async def test_detect_changes_returns_changeset(connector):
    result = await connector.detect_changes(cursor=None)
    assert isinstance(result, ChangeSet)
    assert result.next_cursor == "0"
    assert result.changed == []
    assert result.deleted_ids == []


async def test_download_returns_downloaded_file(connector):
    files = [f async for f in connector.discover()]
    downloaded = await connector.download(files[0])
    assert isinstance(downloaded, DownloadedFile)
    assert len(downloaded.content) > 0
    assert len(downloaded.checksum) == 64  # sha256 hex digest
