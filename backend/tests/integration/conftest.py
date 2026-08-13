import uuid

import pytest
from sqlalchemy.orm import Session

from app.ai.llm.base import LLMResponse
from app.connectors.google_drive import mock_client as mock_client_module
from app.db.session import SessionLocal
from app.models.sync_state import ConnectorAccount, ConnectorMode, ConnectorType
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole


@pytest.fixture(autouse=True, scope="module")
def reset_mock_drive_state():
    """The mock connector's fixture corpus is process-global (one shared
    "Google Drive" for the whole app in this milestone). Reset it once per
    test module so tests start from a known baseline."""
    mock_client_module._STATE_PATH.unlink(missing_ok=True)
    yield
    mock_client_module._STATE_PATH.unlink(missing_ok=True)


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def make_workspace(db: Session, name: str) -> tuple[Workspace, User, ConnectorAccount]:
    suffix = uuid.uuid4().hex[:8]
    workspace = Workspace(name=name, slug=f"{name.lower()}-{suffix}")
    db.add(workspace)
    db.flush()

    user = User(email=f"user-{suffix}@test.local", hashed_password="not-used")
    db.add(user)
    db.flush()

    db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.member))

    connector_account = ConnectorAccount(
        workspace_id=workspace.id,
        connector_type=ConnectorType.google_drive,
        mode=ConnectorMode.mock,
        display_name="Google Drive (Mock)",
    )
    db.add(connector_account)
    db.flush()
    db.commit()
    return workspace, user, connector_account


@pytest.fixture
def workspace_factory(db: Session):
    def _make(name: str = "test-workspace"):
        return make_workspace(db, name)

    return _make


def run_sync_pipeline_inline(connector_account_id: uuid.UUID) -> dict:
    """Runs sync -> process -> embed synchronously, calling task bodies
    directly instead of through Celery's broker -- avoids needing a live
    worker process for tests while exercising the exact same code paths."""
    from app.services.sync_service import SyncService
    from app.workers.task_utils import remote_file_to_dict
    from app.workers.tasks_ingestion import embed_chunk_batch_task, process_document_task

    db = SessionLocal()
    try:
        change_set = SyncService(db).run_sync(connector_account_id)
        db.commit()
    finally:
        db.close()

    results = []
    for remote_file in change_set.changed:
        result = process_document_task.run(str(connector_account_id), remote_file_to_dict(remote_file))
        if result["status"] == "processing":
            embed_chunk_batch_task.run(result["document_version_id"])
        results.append(result)

    return {"change_set": change_set, "results": results}


@pytest.fixture
def sync_pipeline():
    return run_sync_pipeline_inline


class StubLLM:
    """Deterministic stand-in for OllamaChatLLM so chat-flow tests don't
    depend on a live Ollama model being pulled."""

    async def generate(self, messages, *, temperature=0.2, max_tokens=1024):
        return LLMResponse(content="stub answer based on the retrieved context", model="stub")

    async def generate_stream(self, messages, **kwargs):
        yield "stub answer"
