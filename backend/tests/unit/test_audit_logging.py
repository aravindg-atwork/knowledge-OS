import logging
import uuid
from types import SimpleNamespace

import pytest

from app.core.audit import log_audit_event
from app.core.errors import PermissionDeniedError
from app.services.document_access_service import DocumentAccessService


def test_log_audit_event_emits_a_record_with_the_event_name_and_fields(caplog):
    with caplog.at_level(logging.INFO, logger="audit"):
        log_audit_event("auth.login.success", user_id="u1", workspace_id="w1")

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.name == "audit"
    assert record.audit_event == "auth.login.success"
    assert record.user_id == "u1"
    assert record.workspace_id == "w1"


class _FakeDocumentRepository:
    def __init__(self, document=None, version=None):
        self._document = document
        self._version = version

    def get_document(self, document_id):
        return self._document

    def get_version(self, version_id):
        return self._version


def _make_document(*, workspace_id, current_version_id=None, is_deleted=False):
    return SimpleNamespace(
        workspace_id=workspace_id,
        current_version_id=current_version_id,
        is_deleted=is_deleted,
        mime_type="text/plain",
    )


def test_document_access_denied_across_workspaces_emits_audit_event(caplog, tmp_path):
    owning_workspace = uuid.uuid4()
    requesting_workspace = uuid.uuid4()
    document_id = uuid.uuid4()
    document = _make_document(workspace_id=owning_workspace)
    service = DocumentAccessService(_FakeDocumentRepository(document=document), settings=None)

    with caplog.at_level(logging.INFO, logger="audit"):
        with pytest.raises(PermissionDeniedError):
            service.get_content(document_id, workspace_id=requesting_workspace)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.audit_event == "document.access.denied"
    assert record.document_id == str(document_id)
    assert record.requesting_workspace_id == str(requesting_workspace)
    assert record.document_workspace_id == str(owning_workspace)


def test_document_access_granted_emits_audit_event(caplog, tmp_path):
    workspace_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    raw_file = tmp_path / "doc.txt"
    raw_file.write_bytes(b"hello world")
    document = _make_document(workspace_id=workspace_id, current_version_id=version_id)
    version = SimpleNamespace(raw_storage_ref=str(raw_file))
    service = DocumentAccessService(
        _FakeDocumentRepository(document=document, version=version), settings=None
    )

    with caplog.at_level(logging.INFO, logger="audit"):
        content, mime_type = service.get_content(document_id, workspace_id=workspace_id)

    assert content == b"hello world"
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.audit_event == "document.access.granted"
    assert record.document_id == str(document_id)
    assert record.workspace_id == str(workspace_id)
