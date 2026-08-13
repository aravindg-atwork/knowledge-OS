from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ConnectorCredential:
    """Opaque credential handed to Connector.authenticate().

    For the mock connector this carries nothing meaningful. A real OAuth-backed
    connector would populate `token` (and refresh metadata) here instead.
    """

    connector_account_id: str
    token: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RemoteFile:
    """A file as seen by a connector's source system, before download."""

    external_id: str
    name: str
    mime_type: str
    modified_time: datetime
    source_url: str
    author: str | None = None
    size_bytes: int = 0
    checksum_hint: str | None = None  # source-reported hash/etag, if available; not authoritative


@dataclass(frozen=True)
class ChangeSet:
    """Result of an incremental change-detection poll."""

    changed: list[RemoteFile]
    deleted_ids: list[str]
    next_cursor: str


@dataclass(frozen=True)
class DownloadedFile:
    """Raw bytes fetched for a RemoteFile, plus the checksum computed over them."""

    content: bytes
    mime_type: str
    checksum: str
