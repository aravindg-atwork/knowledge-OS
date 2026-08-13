import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_dev_environment_allows_default_secret():
    settings = Settings(ENVIRONMENT="dev", JWT_SECRET="dev-secret-change-me")
    assert settings.JWT_SECRET == "dev-secret-change-me"


def test_non_dev_environment_rejects_default_secret():
    with pytest.raises(ValidationError, match="default dev value"):
        Settings(ENVIRONMENT="production", JWT_SECRET="dev-secret-change-me")


def test_non_dev_environment_rejects_short_secret():
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(ENVIRONMENT="production", JWT_SECRET="too-short")


def test_non_dev_environment_accepts_strong_secret():
    strong_secret = "a" * 32
    settings = Settings(ENVIRONMENT="production", JWT_SECRET=strong_secret)
    assert settings.JWT_SECRET == strong_secret
