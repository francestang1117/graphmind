"""Turn a public URL into a document GraphMind can index."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

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
    # Page chrome. Keep this list conservative so we do not strip article
    # content just because a site picked an unfortunate class name.
    NOISE_SELECTORS = [
        "[role='navigation']",
        "[role='search']",
        "[aria-label*='breadcrumb' i]",
        "[class*='sidebar' i]",
        "[id*='sidebar' i]",
        "[class*='breadcrumb' i]",
        "[id*='breadcrumb' i]",
        "[class*='toc' i]",
        "[id*='toc' i]",
        "[class*='table-of-contents' i]",
        "[id*='table-of-contents' i]",
        "[class*='search' i]",
        "[id*='search' i]",
        "[class*='theme' i]",
        "[id*='theme' i]",
        "[class*='menu' i]",
        "[id*='menu' i]",
        "[class*='pagination' i]",
        "[id*='pagination' i]",
        "[class*='related' i]",
        "[id*='related' i]",
        "[class*='advert' i]",
        "[id*='advert' i]",
        "[class*='cookie' i]",
        "[id*='cookie' i]",
        "[class*='banner' i]",
        "[id*='banner' i]",
        ".sphinxsidebar",
        ".headerlink",
        ".skip-link",
    ]
    # Ordered from most explicit to broadest. Docs pages and rendered Markdown
    # tend to advertise their main body if we ask in the right places.
    MAIN_SELECTORS = [
        "main[role='main']",
        "article",
        "main",
        "[itemprop='articleBody']",
        ".markdown-body",
        ".post-content",
        ".entry-content",
        ".article-content",
        ".document",
        ".body",
        ".content",
        "#content",
        "#main",
        "#article",
    ]
    UI_TEXT_LINES = {
        "next",
        "previous",
        "search",
        "navigation",
        "theme",
        "auto",
        "light",
        "dark",
        "menu",
        "contents",
        "index",
        "back to top",
        "edit this page",
        "skip to content",
        "toggle navigation",
    }
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
        text = self._extract_text(html, final_url)
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
        # The scraper stores text for the parser. PDFs/images/downloads should
        # still go through the upload path where file validation already exists.
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

        # Validate the resolved IP, not just the hostname string. Names like
        # "safe-looking.example" can still resolve to a private address.
        addresses = await asyncio.to_thread(_resolve_host, parsed.hostname)
        if not addresses:
            raise WebScrapeError("This URL could not be resolved.", details={"host": parsed.hostname})

        blocked = [addr for addr in addresses if _is_blocked_address(addr)]
        if blocked:
            raise WebScrapeError(
                "This URL points to a private or local network address.",
                details={"host": parsed.hostname},
            )

    def _extract_text(self, html: str, base_url: str = "") -> str:
        # Reader-mode first, local cleanup if it gives up.
        html = _readability_summary(html) or html
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(list(self.SKIP_TAGS)):
            tag.decompose()
        # Drop obvious site furniture before choosing the main block, otherwise
        # a large sidebar can win the "largest readable block" fallback below.
        for tag in soup.select(", ".join(self.NOISE_SELECTORS)):
            tag.decompose()

        main = self._find_main_content(soup)
        # Keep enough structure for the Markdown parser to do useful work.
        return self._extract_markdown(main, base_url)

    def _find_main_content(self, soup: BeautifulSoup):
        # This is still rule-based, but these selectors cover the pages this
        # project is likely to ingest first: docs sites, blogs, and GitHub-like
        # rendered Markdown.
        for selector in self.MAIN_SELECTORS:
            match = soup.select_one(selector)
            if match and _word_count(match.get_text(" ")) >= 20:
                return match

        # If the site uses custom classes, pick the largest readable block
        # instead of the whole body. It is a small approximation of readability.
        candidates = soup.find_all(["article", "main", "section", "div"])
        best = max(candidates, key=lambda tag: _word_count(tag.get_text(" ")), default=None)
        if best and _word_count(best.get_text(" ")) >= 20:
            return best
        return soup.find("body") or soup

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return " ".join(soup.title.string.split())
        h1 = soup.find("h1")
        return " ".join(h1.get_text(" ").split()) if h1 else ""

    def _clean_text(self, text: str) -> str:
        lines = []
        for raw_line in text.splitlines():
            line = _clean_inline_text(raw_line)
            if not line:
                continue
            # Keep this narrow; these words show up in real prose too.
            if _looks_like_ui_line(line, self.UI_TEXT_LINES):
                continue
            lines.append(line)
        return " ".join(lines)

    def _extract_markdown(self, main, base_url: str = "") -> str:
        blocks = []
        # This is not trying to be a full HTML-to-Markdown converter yet. It
        # just keeps the parts that matter most for chunking: headings, prose,
        # and simple lists.
        for tag in main.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre"]):
            if tag.name == "pre":
                # Keep code as code, not another paragraph.
                code = _clean_code_text(tag.get_text("\n"))
                if code:
                    language = _code_language(tag)
                    blocks.append(f"```{language}\n{code}\n```")
                continue

            text = _markdown_inline_text(tag, base_url)
            if not text or _looks_like_ui_line(text, self.UI_TEXT_LINES):
                continue

            if tag.name.startswith("h"):
                # Keep headings as Markdown so the parser can recover sections
                # instead of seeing the page as one long paragraph.
                level = min(int(tag.name[1]), 6)
                blocks.append(f"{'#' * level} {text}")
            elif tag.name == "li":
                blocks.append(f"- {text}")
            else:
                blocks.append(text)

        if blocks:
            return "\n\n".join(blocks)
        return self._clean_text(main.get_text(separator="\n"))


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
    # Keep the source recognizable in the UI without trusting the page title as
    # a filesystem name.
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:48] or "page"
    return f"web-{host}-{slug}.md"


def _document_text(page: ScrapedPage) -> str:
    return f"# {page.title}\n\nSource: {page.final_url}\n\n{page.text}\n"


def _word_count(text: str) -> int:
    return len(text.split())


def _clean_inline_text(text: str) -> str:
    return " ".join(text.split())


def _readability_summary(html: str) -> str:
    try:
        from readability import Document
    except ImportError:
        return ""

    try:
        # Nice when it works; optional when it does not.
        return Document(html).summary(html_partial=True)
    except Exception as exc:
        log.debug("readability extraction failed: %s", exc)
        return ""


def _markdown_inline_text(tag, base_url: str = "") -> str:
    clone = BeautifulSoup(str(tag), "html.parser")
    for link in clone.find_all("a"):
        label = _clean_inline_text(link.get_text(" "))
        href = _safe_link(link.get("href", ""), base_url)
        # Keep useful source links, but do not let odd schemes leak into the
        # generated Markdown.
        link.replace_with(f"[{label}]({href})" if label and href else label)
    return _clean_inline_text(clone.get_text(" "))


def _safe_link(href: str, base_url: str = "") -> str:
    if not href:
        return ""
    resolved = urljoin(base_url, href)
    scheme = urlparse(resolved).scheme.lower()
    # Body links are useful metadata; javascript/mailto/etc. are not.
    return resolved if scheme in {"http", "https"} else ""


def _clean_code_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _code_language(tag) -> str:
    classes = list(tag.get("class", []))
    code = tag.find("code")
    if code:
        classes.extend(code.get("class", []))

    # Common docs-generator class names; leave blank if none match.
    for cls in classes:
        match = re.match(r"(?:language|lang|highlight)-(.+)", cls)
        if match:
            return match.group(1).lower()
    return ""


def _looks_like_ui_line(line: str, blocked_lines: set[str]) -> bool:
    normalized = re.sub(r"\s+", " ", line).strip().lower()
    if normalized in blocked_lines:
        return True
    # Common tiny control clusters from docs themes.
    if len(normalized.split()) <= 4 and normalized in {
        "next previous",
        "previous next",
        "light dark",
        "auto light dark",
        "show source",
        "view source",
    }:
        return True
    return False


web_scraper = WebScraper()
