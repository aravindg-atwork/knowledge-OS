import hashlib
import secrets
from datetime import UTC, datetime

_TOKEN_BYTES = 32


def generate_token() -> str:
    """Raw token for an emailed link. Never stored -- only its hash is."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(raw: str) -> str:
    """SHA-256 hex digest. A database read cannot be turned into account
    takeover because the raw token exists only inside the emailed link."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)
