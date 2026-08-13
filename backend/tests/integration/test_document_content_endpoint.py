from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import create_app
from app.models.document import Document


def test_content_endpoint_returns_cached_bytes_and_enforces_workspace_scope(
    db, workspace_factory, sync_pipeline
):
    workspace_a, user_a, connector_a = workspace_factory("content-endpoint-a")
    workspace_b, user_b, _connector_b = workspace_factory("content-endpoint-b")
    sync_pipeline(connector_a.id)

    document = (
        db.query(Document)
        .filter(Document.connector_account_id == connector_a.id, Document.external_id == "mock-drive-001")
        .one()
    )

    client = TestClient(create_app())

    token_a = create_access_token(user_a.id, workspace_a.id)
    response = client.get(
        f"/api/v1/documents/{document.id}/content",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert len(response.content) > 0

    token_b = create_access_token(user_b.id, workspace_b.id)
    forbidden_response = client.get(
        f"/api/v1/documents/{document.id}/content",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert forbidden_response.status_code == 403
