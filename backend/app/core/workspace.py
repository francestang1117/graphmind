"""Workspace ids used by the compatibility layer."""

from __future__ import annotations

import hashlib


DEFAULT_WORKSPACE_NAME = "Default workspace"
DEFAULT_WORKSPACE_DOMAIN = "medical"
DEFAULT_WORKSPACE_STATUS = "active"


def default_workspace_id(user_id: str) -> str:
    """Keep one stable default project for each user."""
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]
    return f"default-{digest}"
