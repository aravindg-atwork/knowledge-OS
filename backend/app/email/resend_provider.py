import httpx

from app.core.errors import TransientConnectorError
from app.email.provider import EmailMessage

_RESEND_ENDPOINT = "https://api.resend.com/emails"


class ResendEmailProvider:
    def __init__(self, api_key: str, from_address: str) -> None:
        self._api_key = api_key
        self._from_address = from_address

    def send(self, message: EmailMessage) -> None:
        try:
            response = httpx.post(
                _RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "from": self._from_address,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.text,
                    "html": message.html,
                },
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TransientConnectorError(f"Resend send failed: {exc}") from exc
