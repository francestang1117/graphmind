"""Resolve the workspace used by the existing document APIs."""

from fastapi import HTTPException

from app.core.workspace import default_workspace_id
from app.services.workspace_repository import workspace_repository


def normalize_workspace_id(workspace_id: object) -> str | None:
    """Turn FastAPI parameter defaults into the plain value used by services."""
    if not isinstance(workspace_id, str):
        return None
    value = workspace_id.strip()
    return value or None


def resolve_workspace_id(user_id: str, workspace_id: str | None = None) -> str:
    """Validate a requested project or return the user's compatibility project."""
    workspace_id = normalize_workspace_id(workspace_id)
    if workspace_id:
        if not workspace_repository.get(workspace_id, user_id):
            raise HTTPException(status_code=404, detail="Workspace not found")
        return workspace_id

    workspace_repository.ensure_default(user_id)
    return default_workspace_id(user_id)
