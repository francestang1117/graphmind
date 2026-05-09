"""Endpoint for adding a public web page to the knowledge base."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, HttpUrl

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.core.rate_limit import scrape_limit
from app.services.web_scraper import web_scraper

router = APIRouter()


class ScrapeRequest(BaseModel):
    url: HttpUrl


class ScrapeResponse(BaseModel):
    filename: str
    original_filename: str
    file_hash: str
    file_size: int
    source_url: str
    title: str
    excerpt: str
    status: str = "indexed"


def _user_id(user: UserRecord) -> str:
    # Direct unit-style calls pass the unresolved Depends object. Keep that
    # path usable without leaking into real authenticated requests.
    return getattr(user, "id", "local-dev")


@router.post("/", response_model=ScrapeResponse)
@scrape_limit
async def scrape_url(
    body: ScrapeRequest,
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> ScrapeResponse:
    """Fetch a public page and store it as a normal Markdown document."""
    metadata = await web_scraper.scrape_and_store(str(body.url), user_id=_user_id(user))
    return ScrapeResponse(
        filename=metadata["stored_filename"],
        original_filename=metadata["original_filename"],
        file_hash=metadata["file_hash"],
        file_size=metadata["file_size"],
        source_url=metadata["source_url"],
        title=metadata["title"],
        excerpt=metadata["excerpt"],
    )


@router.post("/scrape", response_model=ScrapeResponse)
@scrape_limit
async def scrape_url_alias(
    body: ScrapeRequest,
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> ScrapeResponse:
    """Compatibility alias while the endpoint shape is still settling."""
    return await scrape_url(body, user, request)
