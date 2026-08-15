import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.connectors.types import ChangeSet, DownloadedFile, RemoteFile
from app.pipeline.checksum import sha256_hex

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
_SEED_PATH = _FIXTURES_DIR / "gmail_seed.json"
_STATE_PATH = _FIXTURES_DIR / ".mock_gmail_state.json"

_BASE_TIME = datetime(2026, 7, 8, tzinfo=UTC)


class MockGmailClient:
    """Fake Gmail inbox backed by a fixture corpus + a mutable revision log,
    same shape as MockGoogleDriveClient. State (revision numbers, deletions)
    persists to a small local JSON file so it survives process restarts
    during development; gitignored, not meant to survive a fresh checkout.
    """

    def __init__(self, state_path: Path | None = None, seed_path: Path | None = None) -> None:
        self._state_path = state_path or _STATE_PATH
        self._seed_path = seed_path or _SEED_PATH
        self._state = self._load_state()

    def set_token(self, access_token: str) -> None:
        pass  # no real auth backing the mock corpus

    async def list_files(self):
        for external_id, entry in self._state["messages"].items():
            if entry["deleted"]:
                continue
            yield self._to_remote_file(external_id, entry)

    async def get_changes(self, cursor: str | None) -> ChangeSet:
        since = int(cursor) if cursor else 0
        changed: list[RemoteFile] = []
        deleted_ids: list[str] = []
        for external_id, entry in self._state["messages"].items():
            if entry["revision"] <= since:
                continue
            if entry["deleted"]:
                deleted_ids.append(external_id)
            else:
                changed.append(self._to_remote_file(external_id, entry))
        return ChangeSet(
            changed=changed,
            deleted_ids=deleted_ids,
            next_cursor=str(self._state["global_revision"]),
        )

    async def download_file(self, external_id: str) -> DownloadedFile:
        entry = self._state["messages"][external_id]
        body = (
            f"Subject: {entry['subject']}\nFrom: {entry['from']}\n"
            f"To: {entry['to']}\n\n{entry['body']}"
        )
        content = body.encode("utf-8")
        return DownloadedFile(
            content=content, mime_type="text/plain", checksum=sha256_hex(content)
        )

    # -- Dev-only simulation hooks --------------------------------------------

    def simulate_delete(self, external_id: str) -> int:
        entry = self._state["messages"][external_id]
        self._state["global_revision"] += 1
        entry["revision"] = self._state["global_revision"]
        entry["deleted"] = True
        self._save_state()
        return entry["revision"]

    def reset_state(self) -> None:
        self._state = self._build_initial_state()
        self._save_state()

    # -- internals --------------------------------------------------------------

    def _to_remote_file(self, external_id: str, entry: dict) -> RemoteFile:
        preview = f"Subject: {entry['subject']}\nFrom: {entry['from']}\n\n{entry['body']}"
        return RemoteFile(
            external_id=external_id,
            name=entry["subject"],
            mime_type="text/plain",
            modified_time=datetime.fromisoformat(entry["date"]),
            source_url=f"mock://gmail/{external_id}",
            author=entry["from"],
            size_bytes=len(preview.encode("utf-8")),
            checksum_hint=sha256_hex(preview.encode("utf-8")),
        )

    def _load_state(self) -> dict:
        if self._state_path.exists():
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        state = self._build_initial_state()
        self._save_state(state)
        return state

    def _build_initial_state(self) -> dict:
        seed = json.loads(self._seed_path.read_text(encoding="utf-8"))
        messages = {}
        for i, item in enumerate(seed["messages"]):
            messages[item["external_id"]] = {
                "subject": item["subject"],
                "from": item["from"],
                "to": item["to"],
                "body": item["body"],
                "revision": 0,
                "date": (_BASE_TIME + timedelta(minutes=i)).isoformat(),
                "deleted": False,
            }
        return {"global_revision": 0, "messages": messages}

    def _save_state(self, state: dict | None = None) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state or self._state, indent=2), encoding="utf-8")
