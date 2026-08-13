from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ChunkPayload:
    """What's stored alongside each chunk's vector in Qdrant. Duplicated here
    (rather than joined from Postgres at query time) so retrieval stays a
    single Qdrant round trip. `workspace_id`/`allowed_roles` are the
    permission-filter fields -- indexed at collection setup for fast filtering.
    """

    document_id: str
    document_version_id: str
    workspace_id: str
    allowed_roles: list[str]
    connector_type: str
    source_title: str
    source_url: str
    mime_type: str
    chunk_index: int
    chunk_text: str
    author: str | None
    source_modified_at: str
    version_number: int
    checksum: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ChunkPayload":
        return cls(**{field: data[field] for field in cls.__dataclass_fields__})
