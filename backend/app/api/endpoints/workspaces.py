"""Research workspace endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.services.workspace_repository import workspace_repository

router = APIRouter()


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    research_question: str = Field(default="", max_length=4000)
    domain: str = Field(default="medical", min_length=1, max_length=64)


class WorkspaceInfo(BaseModel):
    id: str
    user_id: str
    name: str
    research_question: str
    domain: str
    status: str
    created_at: str
    updated_at: str


def _user_id(user: UserRecord) -> str:
    return getattr(user, "id", "local-dev")


@router.post("/", response_model=WorkspaceInfo, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    user: UserRecord = Depends(current_user_or_dev),
) -> WorkspaceInfo:
    """Create a project boundary for one user's research."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workspace name is required")
    return WorkspaceInfo(
        **workspace_repository.create(
            _user_id(user),
            name,
            body.research_question,
            body.domain,
        )
    )


@router.get("/", response_model=list[WorkspaceInfo])
async def list_workspaces(
    user: UserRecord = Depends(current_user_or_dev),
) -> list[WorkspaceInfo]:
    """List only the projects owned by the current account."""
    return [WorkspaceInfo(**item) for item in workspace_repository.list(_user_id(user))]


@router.get("/{workspace_id}", response_model=WorkspaceInfo)
async def get_workspace(
    workspace_id: str,
    user: UserRecord = Depends(current_user_or_dev),
) -> WorkspaceInfo:
    """Return one workspace when it belongs to the current account."""
    workspace = workspace_repository.get(workspace_id, _user_id(user))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceInfo(**workspace)
