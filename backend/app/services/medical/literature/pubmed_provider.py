"""Small, defensive client for the public NCBI PubMed E-utilities API."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import json
import random
import re
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx

from app.core.config import settings
from app.services.medical.literature.exceptions import (
    LiteratureConfigurationError,
    LiteratureProviderError,
)
from app.services.medical.literature.models import LiteratureArticle, LiteratureQuery, LiteratureSearchPage
from app.services.medical.literature.normalizer import (
    clean_text,
    deduplicate_articles,
    metadata_hash,
    normalize_date_parts,
    normalize_doi,
)
from app.services.medical.literature.rate_limiter import (
    PubMedRateLimitUnavailable,
    PubMedRateLimiter,
    get_pubmed_rate_limiter,
)


PUBMED_HOST = "eutils.ncbi.nlm.nih.gov"
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_PMID = re.compile(r"^\d+$")


class PubMedProvider:
    """Fetch only public PubMed metadata and abstracts.

    The provider deliberately uses ESearch followed by one batch EFetch. It
    does not fetch article full text, follow redirects, or log request terms.
    """

    name = "pubmed"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        tool: str | None = None,
        email: str | None = None,
        timeout_seconds: int | None = None,
        max_results: int | None = None,
        retry_count: int | None = None,
        max_response_bytes: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        rate_limiter: PubMedRateLimiter | Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        min_request_interval: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.PUBMED_BASE_URL).rstrip("/")
        self.api_key = (api_key if api_key is not None else settings.PUBMED_API_KEY).strip()
        self.tool = clean_text(tool if tool is not None else settings.PUBMED_TOOL)
        self.email = clean_text(email if email is not None else settings.PUBMED_EMAIL)
        self.timeout_seconds = max(
            1,
            int(timeout_seconds if timeout_seconds is not None else settings.PUBMED_TIMEOUT_SECONDS),
        )
        self.max_results = max(
            1,
            min(
                int(max_results if max_results is not None else settings.PUBMED_MAX_RESULTS),
                50,
            ),
        )
        self.retry_count = max(
            0,
            min(int(retry_count if retry_count is not None else settings.PUBMED_RETRY_COUNT), 5),
        )
        self.max_response_bytes = max(
            1024,
            int(
                max_response_bytes
                if max_response_bytes is not None
                else settings.PUBMED_MAX_RESPONSE_BYTES
            ),
        )
        self.transport = transport
        self._rate_limiter = rate_limiter
        self._use_default_rate_limiter = (
            self._rate_limiter is None and min_request_interval is None
        )
        self._owns_rate_limiter = False
        self.sleep = sleep
        self.jitter = jitter
        self.min_request_interval = float(min_request_interval or 0)
        self._last_request_at = 0.0
        self._pacer = asyncio.Lock()

    def validate_configuration(self) -> None:
        """Reject malformed endpoints before any user query leaves the app."""
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise LiteratureConfigurationError(
                "PubMed endpoint configuration is invalid.",
                code="literature_provider_not_configured",
            )
        # A custom transport is used only by tests. Normal application code
        # may contact the official NCBI host, never an arbitrary URL.
        if self.transport is None and parsed.hostname.lower() != PUBMED_HOST:
            raise LiteratureConfigurationError(
                "PubMed endpoint configuration is not allowed.",
                code="literature_provider_not_configured",
            )
        if not self.tool:
            raise LiteratureConfigurationError(
                "PubMed tool identification is missing.",
                code="literature_provider_not_configured",
            )
        if self.timeout_seconds <= 0 or self.max_response_bytes <= 0:
            raise LiteratureConfigurationError(
                "PubMed request limits are invalid.",
                code="literature_provider_not_configured",
            )

    async def search(self, query: LiteratureQuery) -> LiteratureSearchPage:
        """Run a bounded search and normalize the returned article metadata."""
        self.validate_configuration()
        if query.provider.strip().lower() != self.name:
            raise LiteratureProviderError(
                "The literature query provider is not supported.",
                code="literature_provider_mismatch",
            )

        if self._use_default_rate_limiter:
            self._rate_limiter = get_pubmed_rate_limiter()
            self._owns_rate_limiter = True
        try:
            return await self._search_impl(query)
        finally:
            await self._release_rate_limiter()

    async def _search_impl(self, query: LiteratureQuery) -> LiteratureSearchPage:
        fetched_at = datetime.now(timezone.utc)
        warnings: list[str] = []
        params: dict[str, str | int] = {
            "db": "pubmed",
            "term": query.normalized_query,
            "retmode": "json",
            "retmax": min(query.max_results, self.max_results),
        }
        if query.sort == "newest":
            params["sort"] = "pub_date"

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            search_payload = await self._request_json(client, "esearch.fcgi", params)
            result = search_payload.get("esearchresult")
            if not isinstance(result, dict):
                raise LiteratureProviderError(
                    "PubMed returned an unusable search response.",
                    code="literature_provider_invalid_response",
                )

            raw_ids = result.get("idlist") or []
            ids = [str(value).strip() for value in raw_ids if _PMID.fullmatch(str(value).strip())]
            ids = ids[: min(query.max_results, self.max_results)]
            total_count = _safe_int(result.get("count"), default=len(ids))
            if not ids:
                return LiteratureSearchPage(
                    articles=[],
                    total_count=max(0, total_count),
                    fetched_at=fetched_at,
                    warnings=([] if total_count == 0 else ["no_usable_article_ids"]),
                )

            xml_bytes = await self._request_bytes(
                client,
                "efetch.fcgi",
                {
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "retmode": "xml",
                },
            )
            articles, parse_warnings = self._parse_articles(xml_bytes, ids, fetched_at)
            warnings.extend(parse_warnings)
            articles = deduplicate_articles(articles)
            if not articles:
                warnings.append("no_usable_articles")
            if not self.email:
                warnings.append("pubmed_email_not_configured")
            return LiteratureSearchPage(
                articles=articles,
                total_count=max(total_count, len(articles)),
                fetched_at=fetched_at,
                warnings=list(dict.fromkeys(warnings)),
            )

    async def _release_rate_limiter(self) -> None:
        if not self._owns_rate_limiter:
            return
        limiter = self._rate_limiter
        self._rate_limiter = None
        self._owns_rate_limiter = False
        close = getattr(limiter, "aclose", None)
        if close is not None:
            await close()

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        params: dict[str, str | int],
    ) -> dict[str, Any]:
        raw = await self._request_bytes(client, endpoint, params)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LiteratureProviderError(
                "PubMed returned an invalid JSON response.",
                code="literature_provider_invalid_response",
            ) from exc
        if not isinstance(payload, dict):
            raise LiteratureProviderError(
                "PubMed returned an invalid JSON response.",
                code="literature_provider_invalid_response",
            )
        return payload

    async def _request_bytes(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        params: dict[str, str | int],
    ) -> bytes:
        request_params = {
            "tool": self.tool,
            **params,
        }
        if self.email:
            request_params["email"] = self.email
        if self.api_key:
            request_params["api_key"] = self.api_key

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        for attempt in range(self.retry_count + 1):
            await self._pace()
            try:
                async with client.stream("GET", url, params=request_params) as response:
                    if response.status_code in _RETRYABLE_STATUSES:
                        if attempt < self.retry_count:
                            await self._backoff(attempt, response.headers.get("Retry-After"))
                            continue
                        raise LiteratureProviderError(
                            "PubMed is temporarily unavailable.",
                            code="literature_provider_unavailable",
                            retryable=True,
                        )
                    if response.status_code < 200 or response.status_code >= 300:
                        raise LiteratureProviderError(
                            "PubMed rejected the literature request.",
                            code="literature_provider_request_rejected",
                        )

                    content_length = _safe_int(
                        response.headers.get("Content-Length"), default=0
                    )
                    if content_length > self.max_response_bytes:
                        raise LiteratureProviderError(
                            "The PubMed response exceeded the configured size limit.",
                            code="literature_provider_response_too_large",
                        )

                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        total_bytes += len(chunk)
                        if total_bytes > self.max_response_bytes:
                            raise LiteratureProviderError(
                                "The PubMed response exceeded the configured size limit.",
                                code="literature_provider_response_too_large",
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if attempt >= self.retry_count:
                    raise LiteratureProviderError(
                        "PubMed could not be reached.",
                        code="literature_provider_unavailable",
                        retryable=True,
                    ) from exc
                await self._backoff(attempt)
                continue

        raise LiteratureProviderError(
            "PubMed search failed.",
            code="literature_provider_unavailable",
            retryable=True,
        )

    async def _pace(self) -> None:
        if self._rate_limiter is not None:
            try:
                await self._rate_limiter.acquire(has_api_key=bool(self.api_key))
            except PubMedRateLimitUnavailable as exc:
                raise LiteratureProviderError(
                    "PubMed rate-limit coordination is unavailable.",
                    code="literature_rate_limiter_unavailable",
                    retryable=True,
                ) from exc
            return
        if self.min_request_interval <= 0:
            return
        async with self._pacer:
            now = asyncio.get_running_loop().time()
            wait_for = self.min_request_interval - (now - self._last_request_at)
            if wait_for > 0:
                await self.sleep(wait_for)
            self._last_request_at = asyncio.get_running_loop().time()

    async def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        retry_seconds = _safe_float(retry_after)
        if retry_seconds is None:
            retry_seconds = min(8.0, 0.25 * (2**attempt)) + (self.jitter() * 0.1)
        await self.sleep(max(0.0, min(retry_seconds, 10.0)))

    @staticmethod
    def _parse_articles(
        xml_bytes: bytes,
        requested_ids: list[str],
        fetched_at: datetime,
    ) -> tuple[list[LiteratureArticle], list[str]]:
        # The response is expected from NCBI, but keep XML expansion and DTD
        # handling out of this boundary if a proxy or test ever returns one.
        xml_bytes = _remove_external_doctype(xml_bytes)
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise LiteratureProviderError(
                "PubMed returned invalid article metadata.",
                code="literature_provider_invalid_response",
            ) from exc

        parsed: dict[str, LiteratureArticle] = {}
        warnings: list[str] = []
        for record in root.findall(".//PubmedArticle"):
            try:
                article = _parse_article(record, fetched_at)
            except (TypeError, ValueError, KeyError):
                warnings.append("article_metadata_skipped")
                continue
            if article is None:
                warnings.append("article_metadata_skipped")
                continue
            parsed[article.external_id] = article

        ordered = [parsed[pmid] for pmid in requested_ids if pmid in parsed]
        return ordered, list(dict.fromkeys(warnings))


def _parse_article(record: ET.Element, fetched_at: datetime) -> LiteratureArticle | None:
    citation = record.find("./MedlineCitation")
    article_node = citation.find("./Article") if citation is not None else None
    if citation is None or article_node is None:
        return None

    pmid = _text(citation.find("./PMID"))
    if not pmid or not _PMID.fullmatch(pmid):
        return None
    title = _text(article_node.find("./ArticleTitle"))
    abstract_parts: list[str] = []
    abstract_node = article_node.find("./Abstract")
    if abstract_node is not None:
        for part in abstract_node.findall("./AbstractText"):
            value = _text(part)
            if not value:
                continue
            label = clean_text(part.attrib.get("Label") or part.attrib.get("NlmCategory"))
            abstract_parts.append(f"{label}: {value}" if label else value)

    journal = _text(article_node.find("./Journal/Title"))
    publication_date, publication_year = _publication_date(article_node)
    authors = _authors(article_node)
    publication_types = [
        value
        for value in (_text(item) for item in article_node.findall("./PublicationTypeList/PublicationType"))
        if value
    ]
    mesh_terms = [
        value
        for value in (_text(item) for item in citation.findall("./MeshHeadingList/MeshHeading/DescriptorName"))
        if value
    ]
    language = _text(article_node.find("./Language")) or "unknown"
    doi, pmcid = _article_ids(record)
    retraction_status = _retraction_status(record, publication_types)
    article = LiteratureArticle(
        source="pubmed",
        external_id=pmid,
        doi=normalize_doi(doi),
        pmcid=pmcid,
        title=title,
        abstract=" ".join(abstract_parts) or None,
        journal=journal,
        publication_date=publication_date,
        publication_year=publication_year,
        authors=authors,
        publication_types=publication_types,
        mesh_terms=mesh_terms,
        language=language,
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        retraction_status=retraction_status,
        metadata_hash="0" * 64,
        fetched_at=fetched_at,
    )
    return article.model_copy(update={"metadata_hash": metadata_hash(article)})


def _publication_date(article_node: ET.Element) -> tuple[str | None, int | None]:
    date_node = article_node.find("./ArticleDate")
    if date_node is None:
        date_node = article_node.find("./Journal/JournalIssue/PubDate")
    if date_node is None:
        return None, None

    year = _text(date_node.find("./Year"))
    month = _text(date_node.find("./Month"))
    day = _text(date_node.find("./Day"))
    medline_date = _text(date_node.find("./MedlineDate"))
    if not year and medline_date:
        year_match = re.search(r"\b(\d{4})\b", medline_date)
        year = year_match.group(1) if year_match else ""
        month_match = re.search(
            r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b",
            medline_date,
            flags=re.IGNORECASE,
        )
        month = month_match.group(1) if month_match else ""
    return normalize_date_parts(year, month, day)


def _authors(article_node: ET.Element) -> list[str]:
    result: list[str] = []
    for author in article_node.findall("./AuthorList/Author"):
        collective = _text(author.find("./CollectiveName"))
        if collective:
            result.append(collective)
            continue
        last = _text(author.find("./LastName"))
        fore = _text(author.find("./ForeName"))
        name = clean_text(f"{last} {fore}")
        if name:
            result.append(name)
    return result


def _article_ids(record: ET.Element) -> tuple[str | None, str | None]:
    doi: str | None = None
    pmcid: str | None = None
    for item in record.findall("./PubmedData/ArticleIdList/ArticleId"):
        kind = clean_text(item.attrib.get("IdType")).casefold()
        value = _text(item)
        if kind == "doi" and value:
            doi = value
        elif kind == "pmc" and value:
            pmcid = value.upper()
    return doi, pmcid


def _retraction_status(record: ET.Element, publication_types: list[str]) -> str:
    lowered = {value.casefold() for value in publication_types}
    statuses: set[str] = set()
    if "retracted publication" in lowered or "retracted article" in lowered:
        statuses.add("retracted")
    if any("expression of concern" in value for value in lowered):
        statuses.add("expression_of_concern")
    if any("retraction of publication" in value for value in lowered):
        statuses.add("retraction_notice")
    if any("erratum" in value or "correction" in value for value in lowered):
        statuses.add("corrected")

    # CommentsCorrectionsList belongs to MedlineCitation and RefType is an
    # attribute on each CommentsCorrections element in the PubMed DTD.
    relation_nodes = record.findall(
        "./MedlineCitation/CommentsCorrectionsList/CommentsCorrections"
    )
    if not relation_nodes:
        # Keep old recorded fixtures readable while the official location
        # above remains the source of truth for current PubMed responses.
        relation_nodes = record.findall(
            "./PubmedData/CommentsCorrectionsList/CommentsCorrections"
        )
    for item in relation_nodes:
        ref_type = clean_text(
            item.attrib.get("RefType") or _text(item.find("./RefType"))
        ).casefold().replace(" ", "")
        if ref_type in {"retractionin", "retractedandrepublishedin"}:
            statuses.add("retracted")
        elif ref_type in {"retractionof", "retractedandrepublishedfrom"}:
            statuses.add("retraction_notice")
        elif ref_type in {"expressionofconcernin", "expressionofconcernfor"}:
            statuses.add("expression_of_concern")
        elif ref_type in {"erratumin", "correctedandrepublishedin", "updatein"}:
            statuses.add("corrected")
        elif ref_type in {
            "erratumfor",
            "correctedandrepublishedfrom",
            "updateof",
        }:
            statuses.add("correction_notice")

    for status in (
        "retracted",
        "retraction_notice",
        "expression_of_concern",
        "corrected",
        "correction_notice",
    ):
        if status in statuses:
            return status
    return "normal"


def _remove_external_doctype(xml_bytes: bytes) -> bytes:
    """Strip only the official external DTD declaration before parsing.

    ElementTree does not need the PubMed DTD to build the metadata tree. An
    external declaration is therefore removed after checking that it has no
    internal subset or entity definition. This keeps normal PubMed XML usable
    without allowing arbitrary entity expansion or fetching a remote DTD.
    """
    upper_xml = xml_bytes.upper()
    if b"<!ENTITY" in upper_xml:
        raise LiteratureProviderError(
            "PubMed returned unsupported XML metadata.",
            code="literature_provider_invalid_response",
        )
    doctype_start = upper_xml.find(b"<!DOCTYPE")
    if doctype_start < 0:
        return xml_bytes
    doctype_end = upper_xml.find(b">", doctype_start)
    if doctype_end < 0:
        raise LiteratureProviderError(
            "PubMed returned unsupported XML metadata.",
            code="literature_provider_invalid_response",
        )
    declaration = upper_xml[doctype_start : doctype_end + 1]
    if b"[" in declaration or not (
        b"DTD.NLM.NIH.GOV" in declaration or b"NCBI.NLM.NIH.GOV" in declaration
    ):
        raise LiteratureProviderError(
            "PubMed returned unsupported XML metadata.",
            code="literature_provider_invalid_response",
        )
    return xml_bytes[:doctype_start] + xml_bytes[doctype_end + 1 :]


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return clean_text(" ".join(element.itertext()))


def _safe_int(value: object, *, default: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _safe_float(value: object) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None
