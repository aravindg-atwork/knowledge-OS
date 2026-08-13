from abc import ABC, abstractmethod

from app.connectors.types import ConnectorCredential


class OAuthTokenProvider(ABC):
    @abstractmethod
    async def get_token(self, credential: ConnectorCredential) -> str:
        """Return a valid bearer token, refreshing if necessary."""


class MockOAuthTokenProvider(OAuthTokenProvider):
    """Returns a static fake token immediately -- no real OAuth flow.

    Swapping to real Google OAuth later means writing a GoogleOAuthTokenProvider
    (using google-auth-oauthlib) and wiring it in via the connector registry;
    GoogleDriveConnector.authenticate() itself doesn't change.
    """

    async def get_token(self, credential: ConnectorCredential) -> str:
        return "mock-token"
