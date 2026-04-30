"""Vector search engine for Module 5.

Implemented:
- chunk indexing from parsed documents
- lightweight local embeddings with cosine similarity
- keyword boost for hybrid search
- context assembly for future chat/RAG

This is intentionally dependency-light. ChromaDB and sentence-transformers are
good future upgrades, but loading them at import time makes the current backend
fragile. The first version uses deterministic hashed term vectors, so search
works in a fresh checkout and can be swapped later behind the same interface.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import math
import re
from typing import Any, Iterable, Optional


VECTOR_SIZE = 384
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.-]*")


@dataclass
class IndexedChunk:
    id: str
    text: str
    document: str
    chunk_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] = field(default_factory=list)


class VectorStore:
    """Small in-memory vector index for the current document pipeline."""

    def __init__(self, vector_size: int = VECTOR_SIZE) -> None:
        self.vector_size = vector_size
        self.chunks: dict[str, IndexedChunk] = {}

    def clear(self) -> None:
        self.chunks.clear()

    def add_chunks(self, chunks: Iterable[dict[str, Any]], document_name: str) -> int:
        """Index parsed text chunks for one document."""
        added = 0
        for index, chunk in enumerate(chunks):
            text = str(chunk.get("text", "")).strip()
            if not text:
                continue
            chunk_id = self._chunk_id(document_name, index, text)
            metadata = {
                key: value
                for key, value in chunk.items()
                if key not in {"text"} and _is_metadata_value(value)
            }
            self.chunks[chunk_id] = IndexedChunk(
                id=chunk_id,
                text=text,
                document=document_name,
                chunk_type=str(chunk.get("type") or chunk.get("chunk_type") or "text"),
                metadata=metadata,
                vector=self.embed(text),
            )
            added += 1
        return added

    def search(
        self,
        query: str,
        n_results: int = 5,
        document_filter: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Run vector similarity search over indexed chunks."""
        if not query.strip():
            return []

        query_vector = self.embed(query)
        results = []
        for chunk in self.chunks.values():
            if document_filter and chunk.document != document_filter:
                continue
            score = cosine_similarity(query_vector, chunk.vector)
            if score <= 0:
                continue
            results.append(self._result(chunk, score))

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:n_results]

    def hybrid_search(
        self,
        query: str,
        n_results: int = 5,
        document_filter: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Blend vector similarity with direct keyword overlap."""
        semantic_results = self.search(query, max(n_results * 3, n_results), document_filter)
        query_terms = set(tokenize(query))

        for result in semantic_results:
            text_terms = set(tokenize(result["text"]))
            keyword_score = len(query_terms & text_terms) / max(len(query_terms), 1)
            result["score"] = round((result["score"] * 0.72 + keyword_score * 0.28) * 100, 1)
            result["tags"] = sorted((query_terms & text_terms))[:4] or [result["chunk_type"]]

        semantic_results.sort(key=lambda item: item["score"], reverse=True)
        return semantic_results[:n_results]

    def get_context_for_qa(self, query: str, n_chunks: int = 5) -> str:
        """Return compact context text for a future chat module."""
        results = self.hybrid_search(query, n_chunks)
        if not results:
            return "No relevant context found."
        return "\n\n---\n\n".join(
            f"[From: {item['document']} | Relevance: {item['score']:.1f}%]\n{item['text']}"
            for item in results
        )

    def embed(self, text: str) -> list[float]:
        """Create a normalized hashed bag-of-words vector."""
        counts = Counter(tokenize(text))
        vector = [0.0] * self.vector_size
        for token, count in counts.items():
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "big") % self.vector_size
            sign = -1.0 if digest[4] % 2 else 1.0
            vector[slot] += sign * (1.0 + math.log(count))
        return normalize(vector)

    def _result(self, chunk: IndexedChunk, score: float) -> dict[str, Any]:
        excerpt = compact_excerpt(chunk.text)
        title = str(chunk.metadata.get("section") or chunk.metadata.get("page") or chunk.chunk_type).title()
        return {
            "id": chunk.id,
            "title": title,
            "type": chunk.chunk_type.upper(),
            "score": round(score, 4),
            "text": chunk.text,
            "excerpt": excerpt,
            "document": chunk.document,
            "source": chunk.document,
            "chunk_type": chunk.chunk_type,
            "metadata": chunk.metadata,
        }

    def _chunk_id(self, document_name: str, index: int, text: str) -> str:
        digest = hashlib.sha1(f"{document_name}:{index}:{text[:80]}".encode("utf-8")).hexdigest()
        return f"chunk_{digest[:16]}"


def tokenize(text: str) -> list[str]:
    """Normalize text into searchable terms with a few useful aliases."""
    aliases = {"js": "javascript", "nodejs": "node.js", "ml": "machine-learning"}
    tokens = []
    for match in TOKEN_RE.finditer(text.lower()):
        token = match.group(0).strip("._-")
        if len(token) < 2:
            continue
        tokens.append(aliases.get(token, token))
    return tokens


def normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude:
        return vector
    return [value / magnitude for value in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return max(0.0, sum(left * right for left, right in zip(a, b)))


def compact_excerpt(text: str, max_len: int = 220) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_len:
        return clean
    return f"{clean[: max_len - 3].rstrip()}..."


def _is_metadata_value(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


vector_store = VectorStore()
