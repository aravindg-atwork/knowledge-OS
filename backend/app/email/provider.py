from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> None: ...


@dataclass
class FakeEmailProvider:
    """Test double. Records sends so tests can assert on real link tokens
    instead of mocking at the transport layer."""

    sent: list[EmailMessage] = field(default_factory=list)

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)
