from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.features.identity.dependencies import csrf_protect, require_approved_user
from app.features.identity.models import User
from app.features.workspaces.schemas import CreateWorkspaceRequest, UpdateWorkspaceRequest, WorkspaceDetailResponse, WorkspaceResponse
from app.features.workspaces.service import attach_video, create_workspace, delete_workspace, detach_video, get_workspace, list_workspaces, update_workspace
from app.platform.database import get_db

router = APIRouter(tags=["workspaces"])


@router.get("/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces_route(owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]):
    return list_workspaces(db, owner)


@router.post("/workspaces", response_model=WorkspaceResponse, status_code=201, dependencies=[Depends(csrf_protect)])
def create_workspace_route(request: CreateWorkspaceRequest, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]):
    return create_workspace(db, owner, request)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceDetailResponse)
def get_workspace_route(workspace_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]):
    return get_workspace(db, owner, workspace_id)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResponse, dependencies=[Depends(csrf_protect)])
def update_workspace_route(workspace_id: UUID, request: UpdateWorkspaceRequest, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]):
    return update_workspace(db, owner, workspace_id, request)


@router.delete("/workspaces/{workspace_id}", status_code=204, dependencies=[Depends(csrf_protect)])
def delete_workspace_route(workspace_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]):
    delete_workspace(db, owner, workspace_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workspaces/{workspace_id}/videos/{video_id}", status_code=204, dependencies=[Depends(csrf_protect)])
def attach_video_route(workspace_id: UUID, video_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]):
    attach_video(db, owner, workspace_id, video_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/workspaces/{workspace_id}/videos/{video_id}", status_code=204, dependencies=[Depends(csrf_protect)])
def detach_video_route(workspace_id: UUID, video_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]):
    detach_video(db, owner, workspace_id, video_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

