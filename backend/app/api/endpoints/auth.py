"""Authentication placeholders.

Auth is planned for a later phase. Keeping this module small makes it clear
that document upload does not depend on login yet.
"""

from fastapi import APIRouter, HTTPException, Request, status


router = APIRouter()


@router.post("/login", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def login() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Authentication is not implemented in this phase.",
    )


async def get_current_user(request: Request) -> dict[str, str]:
    """Development-only user shim for future authenticated endpoints."""
    return {"id": "local-dev", "email": "local@example.com"}
