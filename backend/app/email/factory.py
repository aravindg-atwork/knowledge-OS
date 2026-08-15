from functools import lru_cache

from app.core.config import get_settings
from app.email.console import ConsoleEmailProvider
from app.email.provider import EmailProvider
from app.email.resend_provider import ResendEmailProvider


@lru_cache(maxsize=1)
def get_email_provider() -> EmailProvider:
    settings = get_settings()
    provider = settings.EMAIL_PROVIDER.lower()
    if provider == "console":
        return ConsoleEmailProvider()
    if provider == "resend":
        if not settings.RESEND_API_KEY:
            raise ValueError("EMAIL_PROVIDER=resend requires RESEND_API_KEY")
        return ResendEmailProvider(settings.RESEND_API_KEY, settings.EMAIL_FROM_ADDRESS)
    raise ValueError(f"Unknown EMAIL_PROVIDER: {provider}")
