from app.connectors.google_drive.mock_client import MockGoogleDriveClient
from app.models.document import Document, DocumentVersion
from app.vectorstore.factory import get_vector_store
from app.core.config import get_settings


def test_simulated_change_creates_new_version_and_retires_old_vectors(
    db, workspace_factory, sync_pipeline
):
    _workspace, _user, connector_account = workspace_factory("change-detect")
    sync_pipeline(connector_account.id)

    document = (
        db.query(Document)
        .filter(Document.connector_account_id == connector_account.id, Document.external_id == "mock-drive-001")
        .one()
    )
    old_version_id = document.current_version_id
    assert old_version_id is not None

    MockGoogleDriveClient().simulate_change(
        "mock-drive-001", new_body="Completely rewritten roadmap content for this test."
    )

    outcome = sync_pipeline(connector_account.id)
    assert len(outcome["change_set"].changed) == 1
    assert outcome["change_set"].changed[0].external_id == "mock-drive-001"

    db.refresh(document)
    new_version_id = document.current_version_id
    assert new_version_id != old_version_id

    versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).all()
    assert len(versions) == 2

    vector_store = get_vector_store(get_settings())
    from qdrant_client.http import models as qmodels

    old_points, _ = vector_store._client.scroll(
        collection_name=vector_store._collection_name,
        scroll_filter=qmodels.Filter(
            must=[qmodels.FieldCondition(key="document_version_id", match=qmodels.MatchValue(value=str(old_version_id)))]
        ),
        limit=10,
    )
    assert old_points == []

    new_points, _ = vector_store._client.scroll(
        collection_name=vector_store._collection_name,
        scroll_filter=qmodels.Filter(
            must=[qmodels.FieldCondition(key="document_version_id", match=qmodels.MatchValue(value=str(new_version_id)))]
        ),
        limit=10,
    )
    assert len(new_points) > 0
