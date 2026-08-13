import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentSummary(BaseModel):
    id: uuid.UUID
    title: str
    mime_type: str
    source_url: str
    version_number: int | None
    updated_at: datetime
