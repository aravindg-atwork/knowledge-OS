import base64
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import docx
from fpdf import FPDF

from app.connectors.types import ChangeSet, DownloadedFile, RemoteFile
from app.pipeline.checksum import sha256_hex

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
_SEED_PATH = _FIXTURES_DIR / "google_drive_seed.json"
_STATE_PATH = _FIXTURES_DIR / ".mock_state.json"

_BASE_TIME = datetime(2026, 7, 1, tzinfo=UTC)


class MockGoogleDriveClient:
    """Fake Google Drive backed by a fixture corpus + a mutable revision log.

    Implements the `GoogleDriveClient` protocol. State (revision numbers,
    content history, deletions) persists to a small local JSON file so the
    "simulate a change" trigger survives across process restarts during
    development; it is not meant to survive a fresh checkout (gitignored).
    """

    def __init__(self, state_path: Path | None = None, seed_path: Path | None = None) -> None:
        self._state_path = state_path or _STATE_PATH
        self._seed_path = seed_path or _SEED_PATH
        self._state = self._load_state()

    # -- GoogleDriveClient protocol -----------------------------------------

    async def list_files(self):
        for external_id, entry in self._state["files"].items():
            if entry["deleted"]:
                continue
            yield self._to_remote_file(external_id, entry)

    async def get_changes(self, page_token: str | None) -> ChangeSet:
        cursor = int(page_token) if page_token else 0
        changed: list[RemoteFile] = []
        deleted_ids: list[str] = []
        for external_id, entry in self._state["files"].items():
            if entry["revision"] <= cursor:
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
        entry = self._state["files"][external_id]
        content = self._encoded_bytes(entry, entry["revision"])
        return DownloadedFile(
            content=content, mime_type=entry["mime_type"], checksum=sha256_hex(content)
        )

    # -- Dev-only simulation hooks -------------------------------------------

    def simulate_change(self, external_id: str, new_body: str | None = None) -> int:
        """Mutates a fixture file's content and bumps its revision, mirroring
        what a real edit + Drive's changes.list() would surface."""
        entry = self._state["files"][external_id]
        self._state["global_revision"] += 1
        new_revision = self._state["global_revision"]
        body = new_body if new_body is not None else entry["content_versions"][
            str(entry["revision"])
        ] + "\n\n[Updated] This section was revised after the initial version."
        entry["revision"] = new_revision
        entry["content_versions"][str(new_revision)] = body
        self._cache_encoded(entry, new_revision, body)
        entry["modified_time"] = datetime.now(UTC).isoformat()
        self._save_state()
        return new_revision

    def simulate_delete(self, external_id: str) -> int:
        entry = self._state["files"][external_id]
        self._state["global_revision"] += 1
        entry["revision"] = self._state["global_revision"]
        entry["deleted"] = True
        entry["modified_time"] = datetime.now(UTC).isoformat()
        self._save_state()
        return entry["revision"]

    def reset_state(self) -> None:
        self._state = self._build_initial_state()
        self._save_state()

    # -- internals ------------------------------------------------------------

    def _to_remote_file(self, external_id: str, entry: dict) -> RemoteFile:
        content = self._encoded_bytes(entry, entry["revision"])
        return RemoteFile(
            external_id=external_id,
            name=entry["name"],
            mime_type=entry["mime_type"],
            modified_time=datetime.fromisoformat(entry["modified_time"]),
            source_url=f"mock://drive/{external_id}",
            author=entry["author"],
            size_bytes=len(content),
            checksum_hint=sha256_hex(content),
        )

    def _load_state(self) -> dict:
        if self._state_path.exists():
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        state = self._build_initial_state()
        self._save_state(state)
        return state

    def _build_initial_state(self) -> dict:
        seed = json.loads(self._seed_path.read_text(encoding="utf-8"))
        files = {}
        for i, item in enumerate(seed["files"]):
            entry = {
                "name": item["name"],
                "mime_type": item["mime_type"],
                "author": item["author"],
                "revision": 0,
                "modified_time": (_BASE_TIME + timedelta(minutes=i)).isoformat(),
                "content_versions": {"0": item["body"]},
                "encoded_versions": {},
                "deleted": False,
            }
            self._cache_encoded(entry, 0, item["body"])
            files[item["external_id"]] = entry
        return {"global_revision": 0, "files": files}

    def _save_state(self, state: dict | None = None) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(state or self._state, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _cache_encoded(entry: dict, revision: int, body: str) -> None:
        # Encoded once per revision and cached, rather than re-encoded on
        # every download: docx/pdf generation embeds timestamps/metadata
        # that aren't byte-stable across repeated calls, which would break
        # checksum-based idempotency if we re-encoded on each download.
        encoded = _encode_content(body, entry["mime_type"])
        entry["encoded_versions"][str(revision)] = base64.b64encode(encoded).decode("ascii")

    @staticmethod
    def _encoded_bytes(entry: dict, revision: int) -> bytes:
        return base64.b64decode(entry["encoded_versions"][str(revision)])


def _encode_content(body: str, mime_type: str) -> bytes:
    paragraphs = [p for p in body.split("\n\n") if p.strip()]

    if mime_type == "text/plain":
        return body.encode("utf-8")

    if mime_type == "application/vnd.google-apps.document":
        html_paragraphs = "".join(f"<p>{p}</p>" for p in paragraphs)
        return f"<html><body>{html_paragraphs}</body></html>".encode()

    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        document = docx.Document()
        for p in paragraphs:
            document.add_paragraph(p)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    if mime_type == "application/pdf":
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        for p in paragraphs:
            pdf.multi_cell(0, 8, p)
            pdf.ln(2)
        return bytes(pdf.output())

    return body.encode("utf-8")
