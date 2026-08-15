from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_current_user_allow_unverified
from app.core.audit import log_audit_event
from app.db.session import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.tenancy_service import TenancyService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class CreateWorkspaceRequest(BaseModel):
    name: str


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    current_user: CurrentUser = Depends(get_current_user_allow_unverified),
    db: Session = Depends(get_db),
) -> list[WorkspaceResponse]:
    out = []
    for membership in TenancyService(db).list_memberships(current_user.user_id):
        workspace = db.get(Workspace, membership.workspace_id)
        out.append(
            WorkspaceResponse(
                id=str(workspace.id),
                name=workspace.name,
                slug=workspace.slug,
                role=membership.role.value,
            )
        )
    return out


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: CreateWorkspaceRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    user = db.get(User, current_user.user_id)
    workspace = TenancyService(db).create_workspace(payload.name, user)
    db.commit()
    log_audit_event(
        "workspace.created", user_id=str(user.id), workspace_id=str(workspace.id)
    )
    return WorkspaceResponse(
        id=str(workspace.id), name=workspace.name, slug=workspace.slug, role="admin"
    )
