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


def test_scraper_prefers_docs_main_content_over_page_chrome():
    html = """
    <html>
      <head><title>Python Docs</title></head>
      <body>
        <div class="sidebar">Navigation index modules next previous Theme Auto Light Dark</div>
        <div role="search">Search docs</div>
        <div class="breadcrumb">Python docs breadcrumbs</div>
        <div class="theme-switcher">Theme Auto Light Dark</div>
        <div class="document">
          <h1>The Python Tutorial</h1>
          <a class="headerlink" href="#the-python-tutorial">¶</a>
          <p>Python is an easy to learn, powerful programming language with efficient high-level data structures.</p>
          <p>This tutorial introduces many of Python's most noteworthy features and gives a good idea of the language.</p>
          <p>Readers can learn modules, packages, virtual environments, and useful tools from the documentation.</p>
        </div>
      </body>
    </html>
    """

    text = WebScraper()._extract_text(html)

    assert "The Python Tutorial" in text
    assert "virtual environments" in text
    assert "Navigation index modules" not in text
    assert "Search docs" not in text
    assert "Python docs breadcrumbs" not in text
    assert "Theme Auto Light Dark" not in text
    assert "¶" not in text


def test_scraper_filters_short_ui_lines_without_dropping_sentences():
    html = """
    <html>
      <body>
        <main>
          <h1>Python Modules</h1>
          <p>Next</p>
          <p>Search</p>
          <p>Back to top</p>
          <p>The next section explains how Python modules can organize reusable code in larger programs.</p>
          <p>Dark themes can be useful, but this sentence is content rather than a theme toggle.</p>
        </main>
      </body>
    </html>
    """

    text = WebScraper()._extract_text(html)

    assert "Python Modules" in text
    assert "The next section explains" in text
    assert "Dark themes can be useful" in text
    assert "Back to top" not in text
    assert " Search " not in f" {text} "


def test_scraper_keeps_basic_markdown_structure():
    html = """
    <html>
      <body>
        <article>
          <h1>Python Tutorial</h1>
          <p>Python is a clear programming language for examples and documentation.</p>
          <h2>Modules</h2>
          <p>Modules help split programs into reusable files.</p>
          <ul>
            <li>Import modules</li>
            <li>Reuse functions</li>
          </ul>
        </article>
      </body>
    </html>
    """

    text = WebScraper()._extract_text(html)

    assert "# Python Tutorial" in text
    assert "## Modules" in text
    assert "- Import modules" in text
    assert "- Reuse functions" in text


def test_scraper_keeps_fenced_code_blocks():
    html = """
    <html>
      <body>
        <article>
          <h1>Python Example</h1>
          <p>This page shows a short Python snippet for the tutorial.</p>
          <pre><code class="language-python">
def greet(name):
    return f"Hello, {name}"
          </code></pre>
        </article>
      </body>
    </html>
    """

    text = WebScraper()._extract_text(html)

    assert "```python" in text
    assert "def greet(name):" in text
    assert 'return f"Hello, {name}"' in text
    assert text.count("```") == 2


def test_scraper_keeps_body_links_as_markdown():
    html = """
    <html>
      <body>
        <article>
          <h1>Python Links</h1>
          <p>Read the <a href="/3/tutorial/modules.html">modules chapter</a> for more examples.</p>
          <p>Unsafe links should keep their label <a href="javascript:alert(1)">without becoming hrefs</a>.</p>
          <p>External references like <a href="https://www.python.org/">Python.org</a> should stay attached.</p>
        </article>
      </body>
    </html>
    """

    text = WebScraper()._extract_text(html, "https://docs.python.org/3/tutorial/index.html")

    assert "[modules chapter](https://docs.python.org/3/tutorial/modules.html)" in text
    assert "[Python.org](https://www.python.org/)" in text
    assert "without becoming hrefs" in text
    assert "javascript:alert" not in text


def test_scraper_uses_readability_when_available(monkeypatch):
    html = """
    <html>
      <body>
        <div class="content">
          <p>Navigation-like page chrome that should be ignored by readability.</p>
        </div>
        <article>
          <h1>Fallback Article</h1>
          <p>This fallback article should not be used when readability returns a cleaner summary.</p>
        </article>
      </body>
    </html>
    """

    monkeypatch.setattr(
        scraper_module,
        "_readability_summary",
        lambda _html: """
          <article>
            <h1>Readability Article</h1>
            <p>Readability selected this cleaner article body for the scraper output.</p>
          </article>
        """,
    )

    text = WebScraper()._extract_text(html)

    assert "# Readability Article" in text
    assert "cleaner article body" in text
    assert "Fallback Article" not in text


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
