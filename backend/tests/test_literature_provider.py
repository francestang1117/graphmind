"""Mocked PubMed E-utilities tests; no external network is used in CI."""

import asyncio
from datetime import datetime, timezone
import json

import httpx
import pytest

from app.services.medical.literature.exceptions import LiteratureProviderError
from app.services.medical.literature.models import LiteratureQuery
from app.services.medical.literature import pubmed_provider as pubmed_provider_module
from app.services.medical.literature.pubmed_provider import PubMedProvider
from app.services.medical.literature.query_builder import build_literature_query


ARTICLE_XML = b"""
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">12345678</PMID>
      <Article>
        <ArticleTitle>Renal outcomes in Fabry disease</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">A short background.</AbstractText>
          <AbstractText Label="RESULTS">The measured outcome was reported.</AbstractText>
        </Abstract>
        <Journal>
          <Title>Journal of Rare Diseases</Title>
          <JournalIssue><PubDate><Year>2024</Year><Month>Jan</Month><Day>2</Day></PubDate></JournalIssue>
        </Journal>
        <AuthorList>
          <Author><LastName>Doe</LastName><ForeName>Jane</ForeName></Author>
          <Author><CollectiveName>Rare Disease Group</CollectiveName></Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Clinical Trial</PublicationType>
        </PublicationTypeList>
        <Language>eng</Language>
      </Article>
      <MeshHeadingList><MeshHeading><DescriptorName>Fabry Disease</DescriptorName></MeshHeading></MeshHeadingList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">https://doi.org/10.1000/Example</ArticleId>
        <ArticleId IdType="pmc">PMC123456</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

RETRACTION_AND_CORRECTION_XML = b"""
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>11111111</PMID>
      <Article>
        <ArticleTitle>Retracted Fabry disease report</ArticleTitle>
        <Journal><Title>Example Journal</Title></Journal>
        <PublicationTypeList><PublicationType>Retracted Publication</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>22222222</PMID>
      <Article>
        <ArticleTitle>Corrected Fabry disease report</ArticleTitle>
        <Journal><Title>Example Journal</Title></Journal>
      </Article>
      <CommentsCorrectionsList>
        <CommentsCorrections RefType="ErratumIn" />
      </CommentsCorrectionsList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

STATUS_XML = b"""
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation><PMID>33333333</PMID><Article><ArticleTitle>Notice</ArticleTitle><Journal><Title>Journal</Title></Journal></Article><CommentsCorrectionsList><CommentsCorrections RefType="RetractionOf" /></CommentsCorrectionsList></MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation><PMID>44444444</PMID><Article><ArticleTitle>Notice</ArticleTitle><Journal><Title>Journal</Title></Journal></Article><CommentsCorrectionsList><CommentsCorrections RefType="ErratumFor" /></CommentsCorrectionsList></MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation><PMID>55555555</PMID><Article><ArticleTitle>Notice</ArticleTitle><Journal><Title>Journal</Title></Journal></Article><CommentsCorrectionsList><CommentsCorrections RefType="ExpressionOfConcernIn" /></CommentsCorrectionsList></MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

EXTERNAL_DTD_XML = b'''<?xml version="1.0"?>
<!DOCTYPE PubmedArticleSet SYSTEM "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">
<PubmedArticleSet />
'''


def _query() -> LiteratureQuery:
    return build_literature_query("What is known about Fabry disease?")


def test_pubmed_provider_batches_ids_and_normalizes_metadata() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(
                200,
                json={"esearchresult": {"count": "1", "idlist": ["12345678"]}},
                request=request,
            )
        return httpx.Response(200, content=ARTICLE_XML, request=request)

    provider = PubMedProvider(
        transport=httpx.MockTransport(handler),
        min_request_interval=0,
        email="researcher@example.org",
        api_key="secret-api-key",
    )
    page = asyncio.run(provider.search(_query()))

    assert len(calls) == 2
    assert calls[0].url.path.endswith("esearch.fcgi")
    assert calls[1].url.path.endswith("efetch.fcgi")
    assert calls[1].url.params["id"] == "12345678"
    assert calls[0].url.params["tool"] == "graphmind"
    assert page.total_count == 1
    assert len(page.articles) == 1
    article = page.articles[0]
    assert article.external_id == "12345678"
    assert article.doi == "10.1000/example"
    assert article.pmcid == "PMC123456"
    assert article.publication_date == "2024-01-02"
    assert article.authors == ["Doe Jane", "Rare Disease Group"]
    assert "RESULTS: The measured outcome was reported." in (article.abstract or "")
    assert article.retraction_status == "normal"
    assert len(article.metadata_hash) == 64


def test_pubmed_provider_uses_the_official_newest_sort_value() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"esearchresult": {"count": "0", "idlist": []}},
            request=request,
        )

    provider = PubMedProvider(
        transport=httpx.MockTransport(handler),
        min_request_interval=0,
    )
    asyncio.run(provider.search(_query().model_copy(update={"sort": "newest"})))

    assert calls[0].url.params["sort"] == "pub_date"


def test_pubmed_provider_does_not_fetch_when_search_has_no_ids() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={"esearchresult": {"count": "0", "idlist": []}},
            request=request,
        )

    provider = PubMedProvider(
        transport=httpx.MockTransport(handler),
        min_request_interval=0,
    )
    page = asyncio.run(provider.search(_query()))

    assert page.articles == []
    assert page.total_count == 0
    assert len(paths) == 1
    assert paths[0].endswith("esearch.fcgi")


def test_pubmed_provider_retries_rate_limit_with_bounded_delay() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(
                200,
                content=json.dumps({"esearchresult": {"count": "0", "idlist": []}}).encode(),
                request=request,
            )
        return httpx.Response(200, content=ARTICLE_XML, request=request)

    async def no_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    provider = PubMedProvider(
        transport=httpx.MockTransport(handler),
        retry_count=1,
        sleep=no_sleep,
        jitter=lambda: 0,
        min_request_interval=0,
    )
    page = asyncio.run(provider.search(_query()))

    assert page.total_count == 0
    assert attempts == 2
    assert sleeps == [0.0]


def test_pubmed_provider_rejects_oversized_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2048, request=request)

    provider = PubMedProvider(
        transport=httpx.MockTransport(handler),
        max_response_bytes=1024,
        min_request_interval=0,
    )
    with pytest.raises(LiteratureProviderError, match="size limit"):
        asyncio.run(provider.search(_query()))


def test_pubmed_provider_rejects_invalid_json_and_xml() -> None:
    async def invalid_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    json_provider = PubMedProvider(
        transport=httpx.MockTransport(invalid_json),
        min_request_interval=0,
    )
    with pytest.raises(LiteratureProviderError, match="invalid JSON"):
        asyncio.run(json_provider.search(_query()))

    async def invalid_xml(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(
                200,
                json={"esearchresult": {"count": "1", "idlist": ["12345678"]}},
                request=request,
            )
        return httpx.Response(200, content=b"<PubmedArticleSet>", request=request)

    xml_provider = PubMedProvider(
        transport=httpx.MockTransport(invalid_xml),
        min_request_interval=0,
    )
    with pytest.raises(LiteratureProviderError, match="invalid article metadata"):
        asyncio.run(xml_provider.search(_query()))


def test_pubmed_provider_rejects_dtd_and_tracks_retraction_status() -> None:
    with pytest.raises(LiteratureProviderError, match="unsupported XML"):
        PubMedProvider._parse_articles(
            b'<!DOCTYPE foo [<!ENTITY x "expanded">]><PubmedArticleSet />',
            [],
            datetime.now(timezone.utc),
        )

    articles, warnings = PubMedProvider._parse_articles(
        RETRACTION_AND_CORRECTION_XML,
        ["11111111", "22222222"],
        datetime.now(timezone.utc),
    )
    assert warnings == []
    assert [article.retraction_status for article in articles] == ["retracted", "corrected"]

    notices, warnings = PubMedProvider._parse_articles(
        STATUS_XML,
        ["33333333", "44444444", "55555555"],
        datetime.now(timezone.utc),
    )
    assert warnings == []
    assert [article.retraction_status for article in notices] == [
        "retraction_notice",
        "correction_notice",
        "expression_of_concern",
    ]


def test_pubmed_provider_accepts_an_official_external_dtd_declaration() -> None:
    articles, warnings = PubMedProvider._parse_articles(
        EXTERNAL_DTD_XML,
        [],
        datetime.now(timezone.utc),
    )

    assert articles == []
    assert warnings == []


def test_multiple_provider_instances_share_the_default_global_limiter(monkeypatch) -> None:
    class RecordingLimiter:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        async def acquire(self, *, has_api_key: bool = False) -> None:
            self.calls.append(has_api_key)

    limiter = RecordingLimiter()
    monkeypatch.setattr(
        pubmed_provider_module,
        "get_pubmed_rate_limiter",
        lambda: limiter,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"esearchresult": {"count": "0", "idlist": []}},
            request=request,
        )

    async def run() -> None:
        providers = [
            PubMedProvider(
                transport=httpx.MockTransport(handler),
            )
            for _ in range(2)
        ]
        await asyncio.gather(*(provider.search(_query()) for provider in providers))

    asyncio.run(run())

    assert limiter.calls == [False, False]
