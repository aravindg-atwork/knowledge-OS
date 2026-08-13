import pytest

from app.connectors.google_drive.mock_client import MockGoogleDriveClient


@pytest.fixture
def client(tmp_path) -> MockGoogleDriveClient:
    return MockGoogleDriveClient(state_path=tmp_path / "state.json")


async def test_no_changes_before_any_simulated_edit(client):
    result = await client.get_changes(page_token="0")
    assert result.changed == []
    assert result.deleted_ids == []
    assert result.next_cursor == "0"


async def test_simulated_change_is_detected(client):
    client.simulate_change("mock-drive-001", new_body="New content for the roadmap.")

    result = await client.get_changes(page_token="0")

    assert len(result.changed) == 1
    assert result.changed[0].external_id == "mock-drive-001"
    assert result.next_cursor == "1"


async def test_calling_again_with_new_cursor_returns_nothing(client):
    client.simulate_change("mock-drive-001")
    first = await client.get_changes(page_token="0")

    second = await client.get_changes(page_token=first.next_cursor)

    assert second.changed == []
    assert second.deleted_ids == []
    assert second.next_cursor == first.next_cursor


async def test_download_reflects_updated_content(client):
    client.simulate_change("mock-drive-003", new_body="Updated swagger spec body.")

    downloaded = await client.download_file("mock-drive-003")

    assert downloaded.content.decode("utf-8") == "Updated swagger spec body."


async def test_simulated_delete_is_detected_and_excluded_from_discovery(client):
    client.simulate_delete("mock-drive-002")

    changes = await client.get_changes(page_token="0")
    files = [f async for f in client.list_files()]

    assert "mock-drive-002" in changes.deleted_ids
    assert all(f.external_id != "mock-drive-002" for f in files)
