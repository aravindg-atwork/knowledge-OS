import pytest

from app.core.config import get_settings
from app.email.console import ConsoleEmailProvider
from app.email.factory import get_email_provider
from app.email.provider import EmailMessage, FakeEmailProvider
from app.email.templates import (
    invite_message,
    password_reset_message,
    verify_email_message,
)


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """`get_settings()` is process-wide `lru_cache`d (app.core.config). The
    factory tests below monkeypatch EMAIL_PROVIDER and need get_settings()
    to observe it, and must not leak a stale Settings instance into tests
    in other modules that run afterward in the same session."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_fake_provider_records_sends():
    provider = FakeEmailProvider()
    msg = EmailMessage(to="a@b.com", subject="Hi", text="body", html="<p>body</p>")
    provider.send(msg)
    assert provider.sent == [msg]


def test_console_provider_logs_without_raising(caplog):
    ConsoleEmailProvider().send(
        EmailMessage(to="a@b.com", subject="Hi", text="click http://x/y", html="<p>x</p>")
    )
    assert "a@b.com" in caplog.text


def test_factory_returns_console_by_default(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    get_email_provider.cache_clear()
    assert isinstance(get_email_provider(), ConsoleEmailProvider)


def test_factory_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "carrier-pigeon")
    get_email_provider.cache_clear()
    with pytest.raises(ValueError, match="carrier-pigeon"):
        get_email_provider()


def test_templates_embed_the_link_in_both_parts():
    link = "https://app.test/verify?token=abc123"
    for msg in (
        verify_email_message("a@b.com", link),
        password_reset_message("a@b.com", link),
        invite_message("a@b.com", "Acme Corp", "boss@acme.com", link),
    ):
        assert link in msg.text
        assert link in msg.html
        assert msg.to == "a@b.com"
        assert msg.subject


def test_invite_template_names_the_workspace_and_inviter():
    msg = invite_message("a@b.com", "Acme Corp", "boss@acme.com", "https://x/y")
    assert "Acme Corp" in msg.text
    assert "boss@acme.com" in msg.text


def test_html_half_escapes_user_controlled_values():
    """workspace_name is chosen at signup and lands in someone else's inbox."""
    msg = invite_message(
        "a@b.com",
        '<img src=x onerror="alert(1)">',
        "boss@acme.com",
        "https://app.test/invite/accept?token=abc",
    )
    assert "<img src=x" not in msg.html
    assert "&lt;img src=x" in msg.html
    # The plain-text half is not escaped -- entities would render literally.
    assert '<img src=x onerror="alert(1)">' in msg.text
