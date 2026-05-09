"""Web scraper checks: readable pages in, unsafe URLs out."""

import pytest

from app.services import web_scraper as scraper_module
from app.services.web_scraper import WebScrapeError, WebScraper


def run(coro):
    import asyncio

    return asyncio.run(coro)


def test_scraper_extracts_readable_article(monkeypatch):
    monkeypatch.setattr(scraper_module, "_resolve_host", lambda _host: {"93.184.216.34"})

    async def fake_fetch(_url):
        return (
            """
            <html>
              <head><title>RAG Notes</title><script>bad()</script></head>
              <body>
                <nav>navigation</nav>
                <article>
                  <h1>RAG Notes</h1>
                  <p>Retrieval augmented generation connects search results with language model answers.</p>
                  <p>FastAPI can expose a small endpoint that stores scraped pages as documents.</p>
                  <p>Python services parse the page and add useful chunks for search and graph views.</p>
                </article>
              </body>
            </html>
            """,
            "https://example.com/rag",
        )

    scraper = WebScraper()
    monkeypatch.setattr(scraper, "_fetch", fake_fetch)

    page = run(scraper.scrape("https://example.com/rag"))

    assert page.title == "RAG Notes"
    assert "Retrieval augmented generation" in page.text
    assert "navigation" not in page.text
    assert "bad()" not in page.text


def test_scraper_blocks_private_network_urls(monkeypatch):
    monkeypatch.setattr(scraper_module, "_resolve_host", lambda _host: {"127.0.0.1"})

    with pytest.raises(WebScrapeError) as exc:
        run(WebScraper().scrape("https://internal.example"))

    assert exc.value.code == "web_scrape_failed"
    assert "private or local network" in exc.value.message


def test_scrape_and_store_uses_document_upload_path(monkeypatch):
    monkeypatch.setattr(scraper_module, "_resolve_host", lambda _host: {"93.184.216.34"})

    async def fake_scrape(_url):
        return scraper_module.ScrapedPage(
            url="https://example.com/post",
            final_url="https://example.com/post",
            title="Search Design",
            text="GraphMind stores scraped pages as searchable Markdown documents with useful source metadata.",
            html="<html></html>",
        )

    saved = {}

    def fake_save_upload(filename, content, user_id="local-dev"):
        saved["filename"] = filename
        saved["content"] = content.decode()
        saved["user_id"] = user_id
        return {
            "stored_filename": "hash.md",
            "original_filename": filename,
            "file_hash": "hash",
            "file_size": len(content),
        }

    scraper = WebScraper()
    monkeypatch.setattr(scraper, "scrape", fake_scrape)
    monkeypatch.setattr(scraper_module.document_service, "save_upload", fake_save_upload)

    metadata = run(scraper.scrape_and_store("https://example.com/post", user_id="user-1"))

    assert metadata["stored_filename"] == "hash.md"
    assert metadata["source_url"] == "https://example.com/post"
    assert saved["filename"].startswith("web-example.com-search-design")
    assert saved["user_id"] == "user-1"
    assert "Source: https://example.com/post" in saved["content"]
