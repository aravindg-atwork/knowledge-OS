from app.core.config import get_settings
from app.models.chunk import Chunk
from app.models.document import Document, DocumentVersion
from app.models.sync_state import SyncCursor
from app.vectorstore.factory import get_vector_store


def test_resyncing_unchanged_content_creates_no_duplicates(db, workspace_factory, sync_pipeline):
    _workspace, _user, connector_account = workspace_factory("noop-resync")
    sync_pipeline(connector_account.id)

    documents = db.query(Document).filter(Document.connector_account_id == connector_account.id).all()
    document_ids = [d.id for d in documents]
    versions_before = db.query(DocumentVersion).filter(DocumentVersion.document_id.in_(document_ids)).count()
    chunks_before = db.query(Chunk).filter(Chunk.document_id.in_(document_ids)).count()

    vector_store = get_vector_store(get_settings())
    points_before = vector_store._client.count(collection_name=vector_store._collection_name).count

    # Force the next sync to run a full discover() again (as if resyncing from
    # scratch) rather than an incremental detect_changes() -- the no-duplicate
    # guarantee should hold either way, since it's enforced by the checksum
    # idempotency gate in the pipeline, not by change-detection cursors.
    db.query(SyncCursor).filter(SyncCursor.connector_account_id == connector_account.id).delete()
    db.commit()

    outcome = sync_pipeline(connector_account.id)

    assert len(outcome["change_set"].changed) == 10
    assert all(r["status"] == "unchanged" for r in outcome["results"])

    versions_after = db.query(DocumentVersion).filter(DocumentVersion.document_id.in_(document_ids)).count()
    chunks_after = db.query(Chunk).filter(Chunk.document_id.in_(document_ids)).count()
    points_after = vector_store._client.count(collection_name=vector_store._collection_name).count

    assert versions_after == versions_before
    assert chunks_after == chunks_before
    assert points_after == points_before
