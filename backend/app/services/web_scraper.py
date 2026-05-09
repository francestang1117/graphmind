"""Turn a public URL into a document GraphMind can index."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.errors import AppError
from app.services.document_service import document_service

log = logging.getLogger(__name__)


class WebScrapeError(AppError):
    status_code = 400
    code = "web_scrape_failed"
    message = "Could not scrape this URL."


@dataclass
class ScrapedPage:
    url: str
    final_url: str
    title: str
    text: str
    html: str


class WebScraper:
    """Small first pass at web ingestion."""

    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript"}
    ALLOWED_SCHEMES = {"http", "https"}
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024
    TIMEOUT_SECONDS = 12

    async def scrape_and_store(self, url: str, user_id: str = "local-dev") -> dict:
        page = await self.scrape(url)
        filename = _filename_for_url(page.final_url, page.title)
        content = _document_text(page).encode("utf-8")
        # Keep scraped pages on the same path as uploads. That gives us hash
        # dedupe, user scoping, parser summaries, search, and graph rebuilds
        # without inventing another storage lane.
        metadata = document_service.save_upload(filename, content, user_id=user_id)
        metadata["source_url"] = page.final_url
        metadata["title"] = page.title
        metadata["excerpt"] = page.text[:280]
        return metadata

    async def scrape(self, url: str) -> ScrapedPage:
        # Check before and after redirects. A public-looking URL can redirect
        # to localhost or cloud metadata endpoints, which is the classic SSRF
        # footgun for scraper features.
        await self._assert_public_url(url)
        html, final_url = await self._fetch(url)
        await self._assert_public_url(final_url)

        title = self._extract_title(html) or urlparse(final_url).netloc
        text = self._extract_text(html)
        if len(text.split()) < 20:
            raise WebScrapeError(
                "This page did not contain enough readable text.",
                details={"url": final_url},
            )
        return ScrapedPage(url=url, final_url=final_url, title=title, text=text, html=html)

    async def _fetch(self, url: str) -> tuple[str, str]:
        headers = {
            "User-Agent": f"{settings.PROJECT_NAME}/0.1 (+local development scraper)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
        }
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(self.TIMEOUT_SECONDS),
            ) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    self._assert_supported_response(response)
                    body = bytearray()
                    # Stream instead of response.text so a huge page cannot sit
                    # in memory before we notice it crossed the limit.
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.MAX_RESPONSE_BYTES:
                            raise WebScrapeError(
                                "This page is too large to ingest.",
                                details={"max_bytes": self.MAX_RESPONSE_BYTES},
                            )
        except WebScrapeError:
            raise
        except httpx.HTTPStatusError as exc:
            raise WebScrapeError(
                f"The page returned HTTP {exc.response.status_code}.",
                details={"url": str(exc.request.url), "status_code": exc.response.status_code},
            ) from exc
        except httpx.HTTPError as exc:
            raise WebScrapeError(
                "The page could not be fetched.",
                details={"url": url, "reason": str(exc)},
            ) from exc

        encoding = response.encoding or "utf-8"
        return bytes(body).decode(encoding, errors="replace"), str(response.url)

    def _assert_supported_response(self, response: httpx.Response) -> None:
        content_type = response.headers.get("content-type", "").split(";")[0].lower()
        if content_type and content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise WebScrapeError(
                "Only readable web pages can be ingested.",
                details={"content_type": content_type},
            )

        content_length = response.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.MAX_RESPONSE_BYTES:
            raise WebScrapeError(
                "This page is too large to ingest.",
                details={"max_bytes": self.MAX_RESPONSE_BYTES},
            )

    async def _assert_public_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in self.ALLOWED_SCHEMES or not parsed.hostname:
            raise WebScrapeError("Only http and https URLs are supported.", details={"url": url})

        addresses = await asyncio.to_thread(_resolve_host, parsed.hostname)
        if not addresses:
            raise WebScrapeError("This URL could not be resolved.", details={"host": parsed.hostname})

        blocked = [addr for addr in addresses if _is_blocked_address(addr)]
        if blocked:
            raise WebScrapeError(
                "This URL points to a private or local network address.",
                details={"host": parsed.hostname},
            )

    def _extract_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(list(self.SKIP_TAGS)):
            tag.decompose()

        # Prefer the author-written body when the page gives us one. If not,
        # fall back gently instead of failing useful but plain pages.
        main = (
            soup.find("article")
            or soup.find("main")
            or soup.find(id=re.compile(r"content|main|article", re.I))
            or soup.find("body")
            or soup
        )
        return " ".join(main.get_text(separator=" ").split())

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return " ".join(soup.title.string.split())
        h1 = soup.find("h1")
        return " ".join(h1.get_text(" ").split()) if h1 else ""


def _resolve_host(hostname: str) -> set[str]:
    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return set()
    return {item[4][0] for item in results}


def _is_blocked_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    # The scraper is for public knowledge sources. Anything local/private is
    # blocked even in development so the behavior matches production.
    return any([
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_reserved,
        ip.is_unspecified,
    ])


def _filename_for_url(url: str, title: str) -> str:
    host = urlparse(url).netloc.replace(":", "_") or "web"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:48] or "page"
    return f"web-{host}-{slug}.md"


def _document_text(page: ScrapedPage) -> str:
    return f"# {page.title}\n\nSource: {page.final_url}\n\n{page.text}\n"


web_scraper = WebScraper()
