import logging

from app.email.provider import EmailMessage

logger = logging.getLogger(__name__)


class ConsoleEmailProvider:
    """Dev provider: prints the email instead of sending it, so local
    development needs no email credentials. Links are readable in
    `docker compose logs backend`."""

    def send(self, message: EmailMessage) -> None:
        logger.info(
            "email.console.send",
            extra={"to": message.to, "subject": message.subject},
        )
        logger.info("--- EMAIL TO %s: %s ---\n%s", message.to, message.subject, message.text)
