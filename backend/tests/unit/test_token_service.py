from datetime import UTC, datetime, timedelta

from app.services.token_service import generate_token, hash_token, is_expired


def test_generated_tokens_are_unique_and_urlsafe():
    tokens = {generate_token() for _ in range(100)}
    assert len(tokens) == 100
    for token in tokens:
        assert token.isascii()
        assert "/" not in token and "+" not in token and "=" not in token
        assert len(token) >= 32


def test_hash_is_stable_and_64_hex_chars():
    raw = generate_token()
    assert hash_token(raw) == hash_token(raw)
    assert len(hash_token(raw)) == 64
    int(hash_token(raw), 16)  # raises if not hex


def test_hash_differs_for_different_tokens():
    assert hash_token(generate_token()) != hash_token(generate_token())


def test_hash_is_not_reversible_to_the_raw_token():
    raw = generate_token()
    assert raw not in hash_token(raw)


def test_expiry_comparison():
    assert is_expired(datetime.now(UTC) - timedelta(seconds=1)) is True
    assert is_expired(datetime.now(UTC) + timedelta(hours=1)) is False


def test_expiry_handles_naive_datetimes_from_the_db():
    # Postgres may hand back a naive datetime depending on driver config;
    # treating it as UTC must not raise.
    assert is_expired(datetime.utcnow() - timedelta(hours=1)) is True
