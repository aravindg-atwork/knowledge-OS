from dataclasses import asdict
from datetime import datetime

from app.connectors.types import RemoteFile

# Shared retry policy for connector/network-bound tasks: back off exponentially,
# give up after 3 attempts and let the failure surface in sync_runs/document_versions
# rather than retrying forever.
CONNECTOR_RETRY_KWARGS = {
    "max_retries": 3,
    "retry_backoff": True,
    "retry_backoff_max": 60,
    "retry_jitter": True,
}


def remote_file_to_dict(remote_file: RemoteFile) -> dict:
    data = asdict(remote_file)
    data["modified_time"] = remote_file.modified_time.isoformat()
    return data


def remote_file_from_dict(data: dict) -> RemoteFile:
    return RemoteFile(
        external_id=data["external_id"],
        name=data["name"],
        mime_type=data["mime_type"],
        modified_time=datetime.fromisoformat(data["modified_time"]),
        source_url=data["source_url"],
        author=data.get("author"),
        size_bytes=data.get("size_bytes", 0),
        checksum_hint=data.get("checksum_hint"),
    )
