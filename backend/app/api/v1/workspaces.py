import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_current_user_allow_unverified,
    invalidate_membership_cache,
    require_admin,
)
from app.core.audit import log_audit_event
from app.db.session import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.tenancy_service import TenancyService, validate_workspace_name

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


class MemberResponse(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: str


class ChangeRoleRequest(BaseModel):
    role: WorkspaceRole


class RenameWorkspaceRequest(BaseModel):
    name: str


@router.get("/current/members", response_model=list[MemberResponse])
def list_members(
    current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> list[MemberResponse]:
    memberships = db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == current_user.workspace_id
        )
    ).all()
    out = []
    for membership in memberships:
        user = db.get(User, membership.user_id)
        out.append(
            MemberResponse(
                user_id=str(user.id),
                email=user.email,
                full_name=user.full_name,
                role=membership.role.value,
            )
        )
    return out


@router.patch("/current/members/{user_id}", response_model=MemberResponse)
def change_member_role(
    user_id: uuid.UUID,
    payload: ChangeRoleRequest,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MemberResponse:
    membership = TenancyService(db).change_role(
        current_user.workspace_id, user_id, payload.role
    )
    db.commit()
    invalidate_membership_cache(user_id, current_user.workspace_id)
    log_audit_event(
        "workspace.member_role_changed",
        actor_user_id=str(current_user.user_id),
        user_id=str(user_id),
        workspace_id=str(current_user.workspace_id),
        role=payload.role.value,
    )
    user = db.get(User, user_id)
    return MemberResponse(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=membership.role.value,
    )


@router.delete("/current/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    TenancyService(db).remove_member(current_user.workspace_id, user_id)
    db.commit()
    invalidate_membership_cache(user_id, current_user.workspace_id)
    log_audit_event(
        "workspace.member_removed",
        actor_user_id=str(current_user.user_id),
        user_id=str(user_id),
        workspace_id=str(current_user.workspace_id),
    )


@router.patch("/current", response_model=WorkspaceResponse)
def rename_workspace(
    payload: RenameWorkspaceRequest,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    workspace = db.get(Workspace, current_user.workspace_id)
    # Same rule as signup -- a rename must not smuggle in what signup rejects.
    workspace.name = validate_workspace_name(payload.name)
    db.commit()
    log_audit_event(
        "workspace.renamed",
        user_id=str(current_user.user_id),
        workspace_id=str(workspace.id),
    )
    return WorkspaceResponse(
        id=str(workspace.id),
        name=workspace.name,
        slug=workspace.slug,
        role=current_user.role.value,
    )
