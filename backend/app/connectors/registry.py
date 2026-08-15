from collections.abc import Callable

from app.connectors.base import Connector
from app.models.sync_state import ConnectorMode, ConnectorType

_FACTORIES: dict[tuple[ConnectorType, ConnectorMode], Callable[[], Connector]] = {}


def register_connector(
    connector_type: ConnectorType, mode: ConnectorMode, factory: Callable[[], Connector]
) -> None:
    _FACTORIES[(connector_type, mode)] = factory


def get_connector(connector_type: ConnectorType, mode: ConnectorMode) -> Connector:
    key = (connector_type, mode)
    if key not in _FACTORIES:
        raise ValueError(f"No connector registered for type={connector_type} mode={mode}")
    return _FACTORIES[key]()


def _real_google_token_provider():
    from app.connectors.google_oauth import GoogleOAuthTokenProvider
    from app.core.config import get_settings

    settings = get_settings()
    return GoogleOAuthTokenProvider(
        settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET
    )


def _register_defaults() -> None:
    from app.connectors.gmail.connector import GmailConnector
    from app.connectors.gmail.mock_client import MockGmailClient
    from app.connectors.gmail.real_client import RealGmailClient
    from app.connectors.google_drive.connector import GoogleDriveConnector
    from app.connectors.google_drive.mock_client import MockGoogleDriveClient
    from app.connectors.google_drive.real_client import RealGoogleDriveClient

    register_connector(
        ConnectorType.google_drive,
        ConnectorMode.mock,
        lambda: GoogleDriveConnector(MockGoogleDriveClient()),
    )
    register_connector(
        ConnectorType.google_drive,
        ConnectorMode.real,
        lambda: GoogleDriveConnector(RealGoogleDriveClient(), _real_google_token_provider()),
    )
    register_connector(
        ConnectorType.gmail,
        ConnectorMode.mock,
        lambda: GmailConnector(MockGmailClient()),
    )
    register_connector(
        ConnectorType.gmail,
        ConnectorMode.real,
        lambda: GmailConnector(RealGmailClient(), _real_google_token_provider()),
    )


_register_defaults()
