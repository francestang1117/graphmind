"""Entity extraction for the first knowledge-graph pass.

Implemented:
- optional spaCy NER for people, organizations, places, dates, and products
- rule-based technical entity extraction
- Markdown-aware concept/link/code extraction
- entity normalization and deduplication
- lightweight relation hints for the future graph builder
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
import re
from typing import Any, Callable, Iterable, Optional, Union


log = logging.getLogger(__name__)
DEFAULT_SPACY_MODEL = "en_core_web_sm"
_SPACY_MODEL_CACHE: dict[str, Any] = {}


@dataclass
class Entity:
    text: str
    label: str
    start: int
    end: int
    confidence: float = 1.0
    source: str = "rule"
    context: str = ""
    normalized: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EntityRelation:
    source: str
    target: str
    relation: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DomainTerm:
    """A curated entity the graph should trust more than raw regex matches."""

    canonical: str
    label: str
    aliases: tuple[str, ...] = ()
    confidence: float = 0.94


SPACY_LABELS = {
    "PERSON": "PERSON",
    "ORG": "ORGANIZATION",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "DATE": "DATE",
    "TIME": "TIME",
    "PRODUCT": "PRODUCT",
    "EVENT": "EVENT",
    "WORK_OF_ART": "WORK",
    "LAW": "LAW",
    "LANGUAGE": "LANGUAGE",
}

STOP_CONCEPTS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "module",
    "file",
    "function",
    "class",
    "return",
    "array",
    "sample",
    "size",
    "value",
    "values",
    "item",
    "items",
    "data",
    "object",
    "option",
    "options",
    "result",
    "config",
    "path",
    "name",
    "type",
}


GENERIC_SINGLE_WORDS = {
    "generate",
    "jargon",
    "method",
    "principle",
    "principles",
    "overview",
    "summary",
    "introduction",
    "example",
    "examples",
    "note",
    "notes",
    "content",
    "section",
    "chapter",
}


GEOGRAPHY_CONTEXT_WORDS = {
    "address",
    "area",
    "country",
    "county",
    "geography",
    "map",
    "province",
    "region",
    "state",
    "street",
}


DOMAIN_RELEVANT_LABELS = {
    "PROGRAMMING_LANGUAGE",
    "FRAMEWORK",
    "LIBRARY",
    "DATABASE",
    "TOOL",
    "CONCEPT",
    "FUNCTION",
    "CLASS",
    "DOCUMENT",
    "REPOSITORY",
}


LABEL_PRIORITY = {
    "PROGRAMMING_LANGUAGE": 100,
    "FRAMEWORK": 95,
    "LIBRARY": 90,
    "DATABASE": 88,
    "TOOL": 86,
    "CONCEPT": 85,
    "ORGANIZATION": 80,
    "PERSON": 80,
    "LOCATION": 75,
    "PRODUCT": 75,
    "CLASS": 70,
    "FUNCTION": 68,
    "DATE": 50,
    "VERSION": 30,
    "RESOURCE": 20,
}


NOISE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^[0-9a-f]{6,}(?:[_-]\d+)?$",
        r"^[a-z0-9]{6,}[_-]\d+$",
        r"^\d+\.\d+\.\d+(?:\s+\S+)?",
        r"^\d{1,2}:\d{2}\s*(?:am|pm)?$",
        r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"^\d+[+\-]$",
        r"^(the|a|an)\s+\S+",
        r"^.{1,2}$",
    )
)


TYPE_PAIR_RELATIONS: dict[tuple[str, str], str] = {
    ("PROGRAMMING_LANGUAGE", "FRAMEWORK"): "HAS_FRAMEWORK",
    ("FRAMEWORK", "PROGRAMMING_LANGUAGE"): "WRITTEN_IN",
    ("PROGRAMMING_LANGUAGE", "LIBRARY"): "HAS_LIBRARY",
    ("LIBRARY", "PROGRAMMING_LANGUAGE"): "WRITTEN_IN",
    ("FRAMEWORK", "LIBRARY"): "USES",
    ("LIBRARY", "FRAMEWORK"): "USED_BY",
    ("FRAMEWORK", "DATABASE"): "USES",
    ("DATABASE", "FRAMEWORK"): "USED_BY",
    ("TOOL", "FRAMEWORK"): "INTEGRATES_WITH",
    ("TOOL", "LIBRARY"): "INTEGRATES_WITH",
    ("PERSON", "ORGANIZATION"): "ASSOCIATED_WITH",
    ("ORGANIZATION", "PERSON"): "ASSOCIATED_WITH",
    ("CONCEPT", "CONCEPT"): "RELATED_TO",
    ("CONCEPT", "FRAMEWORK"): "RELATED_TO",
    ("CONCEPT", "PROGRAMMING_LANGUAGE"): "RELATED_TO",
    ("CONCEPT", "DATABASE"): "RELATED_TO",
    ("CONCEPT", "TOOL"): "RELATED_TO",
}


# This is intentionally small and explicit. It gives Module 3 useful signal now,
# while leaving room for a richer taxonomy or user-provided glossary later.
TECH_TERMS: dict[str, str] = {
    "python": "PROGRAMMING_LANGUAGE",
    "javascript": "PROGRAMMING_LANGUAGE",
    "js": "PROGRAMMING_LANGUAGE",
    "typescript": "PROGRAMMING_LANGUAGE",
    "java": "PROGRAMMING_LANGUAGE",
    "c++": "PROGRAMMING_LANGUAGE",
    "c#": "PROGRAMMING_LANGUAGE",
    "go": "PROGRAMMING_LANGUAGE",
    "rust": "PROGRAMMING_LANGUAGE",
    "node.js": "FRAMEWORK",
    "nodejs": "FRAMEWORK",
    "react": "FRAMEWORK",
    "vue": "FRAMEWORK",
    "angular": "FRAMEWORK",
    "django": "FRAMEWORK",
    "flask": "FRAMEWORK",
    "fastapi": "FRAMEWORK",
    "tensorflow": "FRAMEWORK",
    "pytorch": "FRAMEWORK",
    "keras": "FRAMEWORK",
    "pandas": "LIBRARY",
    "numpy": "LIBRARY",
    "spacy": "LIBRARY",
    "lodash": "LIBRARY",
    "chromadb": "DATABASE",
    "neo4j": "DATABASE",
    "postgresql": "DATABASE",
    "redis": "DATABASE",
    "docker": "TOOL",
    "celery": "FRAMEWORK",
    "json": "CONCEPT",
    "http": "CONCEPT",
    "markdown": "CONCEPT",
    "json5": "LIBRARY",
    "llm": "CONCEPT",
    "large language model": "CONCEPT",
    "machine learning": "CONCEPT",
    "ml": "CONCEPT",
    "deep learning": "CONCEPT",
    "neural network": "CONCEPT",
    "artificial intelligence": "CONCEPT",
    "natural language processing": "CONCEPT",
    "computer vision": "CONCEPT",
    "knowledge graph": "CONCEPT",
    "knowledge base": "CONCEPT",
    "entity extraction": "CONCEPT",
    "named entity recognition": "CONCEPT",
    "ner": "CONCEPT",
    "semantic search": "CONCEPT",
    "hybrid search": "CONCEPT",
    "retrieval augmented generation": "CONCEPT",
    "rag": "CONCEPT",
    "chunking": "CONCEPT",
    "embedding": "CONCEPT",
    "embeddings": "CONCEPT",
    "vector embedding": "CONCEPT",
    "reranking": "CONCEPT",
    "document ingestion": "CONCEPT",
    "text extraction": "CONCEPT",
    "api": "CONCEPT",
    "graphql": "CONCEPT",
    "rest": "CONCEPT",
    "database": "CONCEPT",
    "graph database": "CONCEPT",
    "vector database": "CONCEPT",
    "array": "CONCEPT",
    "sampling": "CONCEPT",
    "data structure": "CONCEPT",
}


CANONICAL_TERMS = {
    "python": "Python",
    "typescript": "TypeScript",
    "react": "React",
    "fastapi": "FastAPI",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "numpy": "NumPy",
    "pandas": "pandas",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "api": "API",
    "rest": "REST",
    "http": "HTTP",
    "json": "JSON",
    "markdown": "Markdown",
    "json5": "JSON5",
    "lodash": "Lodash",
    "llm": "Large Language Model",
    "rag": "Retrieval Augmented Generation",
    "ner": "Named Entity Recognition",
    "chromadb": "ChromaDB",
    "neo4j": "Neo4j",
    "postgresql": "PostgreSQL",
    "redis": "Redis",
    "docker": "Docker",
    "celery": "Celery",
}


DOMAIN_TERMS: tuple[DomainTerm, ...] = (
    DomainTerm("Python", "PROGRAMMING_LANGUAGE", ("python",)),
    DomainTerm("JavaScript", "PROGRAMMING_LANGUAGE", ("javascript", "js")),
    DomainTerm("TypeScript", "PROGRAMMING_LANGUAGE", ("typescript", "ts")),
    DomainTerm("Java", "PROGRAMMING_LANGUAGE", ("java",)),
    DomainTerm("Go", "PROGRAMMING_LANGUAGE", ("go", "golang")),
    DomainTerm("Rust", "PROGRAMMING_LANGUAGE", ("rust",)),
    DomainTerm("React", "FRAMEWORK", ("react", "reactjs")),
    DomainTerm("Vue", "FRAMEWORK", ("vue", "vue.js", "vuejs")),
    DomainTerm("Angular", "FRAMEWORK", ("angular",)),
    DomainTerm("FastAPI", "FRAMEWORK", ("fastapi",)),
    DomainTerm("Django", "FRAMEWORK", ("django",)),
    DomainTerm("Flask", "FRAMEWORK", ("flask",)),
    DomainTerm("Node.js", "FRAMEWORK", ("node.js", "nodejs")),
    DomainTerm("TensorFlow", "FRAMEWORK", ("tensorflow",)),
    DomainTerm("PyTorch", "FRAMEWORK", ("pytorch",)),
    DomainTerm("Keras", "FRAMEWORK", ("keras",)),
    DomainTerm("NumPy", "LIBRARY", ("numpy",)),
    DomainTerm("pandas", "LIBRARY", ("pandas",)),
    DomainTerm("spaCy", "LIBRARY", ("spacy", "spaCy")),
    DomainTerm("Lodash", "LIBRARY", ("lodash",)),
    DomainTerm("ChromaDB", "DATABASE", ("chromadb", "chroma")),
    DomainTerm("Neo4j", "DATABASE", ("neo4j",)),
    DomainTerm("PostgreSQL", "DATABASE", ("postgresql", "postgres")),
    DomainTerm("Redis", "DATABASE", ("redis",)),
    DomainTerm("Docker", "TOOL", ("docker", "docker compose")),
    DomainTerm("Celery", "FRAMEWORK", ("celery",)),
    DomainTerm("API", "CONCEPT", ("api", "apis")),
    DomainTerm("REST", "CONCEPT", ("rest", "rest api", "restful")),
    DomainTerm("HTTP", "CONCEPT", ("http", "https")),
    DomainTerm("JSON", "CONCEPT", ("json",)),
    DomainTerm("JSON5", "LIBRARY", ("json5",)),
    DomainTerm("Markdown", "CONCEPT", ("markdown",)),
    DomainTerm("GraphQL", "CONCEPT", ("graphql",)),
    DomainTerm("Database", "CONCEPT", ("database", "databases")),
    DomainTerm("Graph Database", "CONCEPT", ("graph database",)),
    DomainTerm("Vector Database", "CONCEPT", ("vector database", "vector db")),
    DomainTerm("Knowledge Graph", "CONCEPT", ("knowledge graph",)),
    DomainTerm("Knowledge Base", "CONCEPT", ("knowledge base",)),
    DomainTerm("Semantic Search", "CONCEPT", ("semantic search",)),
    DomainTerm("Hybrid Search", "CONCEPT", ("hybrid search",)),
    DomainTerm("Retrieval Augmented Generation", "CONCEPT", ("retrieval augmented generation", "rag")),
    DomainTerm("Large Language Model", "CONCEPT", ("large language model", "llm", "llms")),
    DomainTerm("Entity Extraction", "CONCEPT", ("entity extraction",)),
    DomainTerm("Named Entity Recognition", "CONCEPT", ("named entity recognition", "ner")),
    DomainTerm("Chunking", "CONCEPT", ("chunking", "chunk", "chunks")),
    DomainTerm("Embedding", "CONCEPT", ("embedding", "embeddings")),
    DomainTerm("Vector Embedding", "CONCEPT", ("vector embedding", "vector embeddings")),
    DomainTerm("Reranking", "CONCEPT", ("reranking", "rerank", "reranker")),
    DomainTerm("Document Ingestion", "CONCEPT", ("document ingestion",)),
    DomainTerm("Text Extraction", "CONCEPT", ("text extraction",)),
    DomainTerm("Machine Learning", "CONCEPT", ("machine learning", "ml")),
    DomainTerm("Deep Learning", "CONCEPT", ("deep learning",)),
    DomainTerm("Neural Network", "CONCEPT", ("neural network", "neural networks")),
    DomainTerm("Artificial Intelligence", "CONCEPT", ("artificial intelligence", "ai")),
    DomainTerm("Natural Language Processing", "CONCEPT", ("natural language processing", "nlp")),
    DomainTerm("Computer Vision", "CONCEPT", ("computer vision",)),
)


DOMAIN_LOOKUP = {
    alias.lower(): term
    for term in DOMAIN_TERMS
    for alias in (term.canonical, *term.aliases)
}


LlmEnhancer = Callable[[str], Iterable[Union[Entity, dict[str, Any]]]]
RelationEnhancer = Callable[[list[Entity], str], Iterable[Union[EntityRelation, dict[str, Any]]]]
SemanticSimilarity = Callable[[str, str], float]


class EntityExtractor:
    """Extract normalized entities from text and parsed documents."""

    def __init__(
        self,
        model_name: Optional[str] = DEFAULT_SPACY_MODEL,
        min_confidence: float = 0.7,
        llm_enhancer: Optional[LlmEnhancer] = None,
        relation_enhancer: Optional[RelationEnhancer] = None,
        semantic_similarity: Optional[SemanticSimilarity] = None,
        semantic_merge_threshold: float = 0.92,
    ) -> None:
        # spaCy is an opportunistic enhancer. If the local model exists, use it;
        # otherwise keep the rule/domain pass running without network downloads.
        self.model_name = model_name
        self.min_confidence = min_confidence
        self.llm_enhancer = llm_enhancer
        self.relation_enhancer = relation_enhancer
        self.semantic_similarity = semantic_similarity
        self.semantic_merge_threshold = semantic_merge_threshold
        self.nlp = self._load_spacy_model(model_name) if model_name else None

    def extract_from_text(self, text: str) -> list[Entity]:
        """Extract entities from plain text using spaCy when available plus rules."""
        if not text.strip():
            return []

        entities = []
        entities.extend(self._extract_with_spacy(text))
        entities.extend(self._extract_domain_terms(text))
        entities.extend(self._extract_versions(text))
        entities.extend(self._extract_repositories(text))
        entities.extend(self._extract_with_llm(text))
        return self._deduplicate(entities)

    def extract_from_markdown(self, parsed_markdown: dict[str, Any]) -> list[Entity]:
        """Use Markdown structure as context instead of flattening everything."""
        entities = []
        # Headings and links are not just text; they are author-selected signals
        # about what the document considers important.
        entities.extend(self._extract_from_headers(parsed_markdown.get("headers", [])))
        entities.extend(self._extract_from_links(parsed_markdown.get("links", [])))
        entities.extend(self._extract_from_code_blocks(parsed_markdown.get("code_blocks", [])))
        entities.extend(self.extract_from_text(parsed_markdown.get("raw_content", "")))
        return self._deduplicate(entities)

    def extract_from_parsed_document(self, parsed: dict[str, Any]) -> list[Entity]:
        """Extract entities from the parser's legacy dict shape."""
        content = parsed.get("content", "")
        extra = parsed.get("extra", {})
        entities = self.extract_from_text(content)
        entities.extend(self._extract_from_code_blocks(extra.get("code_blocks", [])))
        entities.extend(self._extract_from_parser_symbols(extra))
        for item in extra.get("entities", []):
            # Some parsers already emit lightweight hints, such as dependencies
            # from code imports or low-cardinality CSV values. Keep those hints
            # but normalize them into the same Entity shape.
            text = item.get("text") if isinstance(item, dict) else ""
            label = item.get("type", "ENTITY") if isinstance(item, dict) else "ENTITY"
            if text:
                entities.append(self._entity(text, label.upper(), 0, len(text), 0.75, "parser"))
        return self._deduplicate(entities)

    def _extract_from_parser_symbols(self, extra: dict[str, Any]) -> list[Entity]:
        """Promote parser structure into graph-worthy entities."""
        entities = []
        for name in extra.get("imports", []):
            clean = self._normalize_js_module(str(name)) if "/" in str(name) else str(name).split(".")[0]
            if clean:
                entities.append(self._entity(clean, "LIBRARY", 0, len(clean), 0.82, "parser"))
        for section in extra.get("sections", []):
            if isinstance(section, dict):
                entities.extend(self._extract_compound_concepts(str(section.get("title") or section.get("header") or "")))
        for name in extra.get("functions", []):
            clean = self._display_symbol_name(str(name).split("(")[0])
            if clean and not clean.startswith((".", "/")):
                entities.append(self._entity(clean, "FUNCTION", 0, len(clean), 0.74, "parser"))
        for name in extra.get("classes", []):
            clean = self._display_symbol_name(str(name))
            if clean:
                entities.append(self._entity(clean, "CLASS", 0, len(clean), 0.78, "parser"))
        return entities

    def _display_symbol_name(self, name: str) -> str:
        """Clean parser symbols without changing the source code itself."""
        return name.strip().lstrip("_")

    def _extract_compound_concepts(self, text: str) -> list[Entity]:
        clean = self._display_symbol_name(text)
        if not clean or clean.lower() in STOP_CONCEPTS:
            return []
        return [self._entity(clean, "CONCEPT", 0, len(clean), 0.64, "parser")]

    def extract_relations(self, entities: list[Entity], text: str) -> list[EntityRelation]:
        """Infer early relation hints from simple patterns and sentence co-occurrence."""
        relations = []
        relations.extend(self._extract_pattern_relations(entities, text))
        relations.extend(self._extract_cooccurrence_relations(entities, text))
        relations.extend(self._extract_with_relation_enhancer(entities, text))
        return self._deduplicate_relations(relations)

    def _extract_with_relation_enhancer(self, entities: list[Entity], text: str) -> list[EntityRelation]:
        """Optional GPT/LLM relation pass. Disabled unless a caller provides it."""
        if self.relation_enhancer is None or len(entities) < 2:
            return []
        try:
            raw_items = self.relation_enhancer(entities, text)
        except Exception:
            return []

        relations = []
        for item in raw_items:
            if isinstance(item, EntityRelation):
                relations.append(item)
                continue
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            target = str(item.get("target") or "").strip()
            relation = str(item.get("relation") or "RELATED_TO").upper()
            confidence = float(item.get("confidence", 0.74) or 0.74)
            if source and target and source != target:
                relations.append(EntityRelation(source, target, relation, confidence))
        return relations

    def _load_spacy_model(self, model_name: str) -> Any:
        if model_name in _SPACY_MODEL_CACHE:
            return _SPACY_MODEL_CACHE[model_name]

        try:
            import spacy
        except ImportError:
            log.info("spaCy is not installed; using rule-based entity extraction only.")
            return None

        try:
            _SPACY_MODEL_CACHE[model_name] = spacy.load(model_name)
            return _SPACY_MODEL_CACHE[model_name]
        except OSError:
            # The model is optional for local development. Rule extraction still
            # gives deterministic results without downloading anything at import.
            log.info("spaCy model %s is not installed; using rule-based extraction only.", model_name)
            return None

    def _extract_with_spacy(self, text: str) -> list[Entity]:
        if self.nlp is None:
            return []

        entities = []
        doc = self.nlp(text)
        for ent in doc.ents:
            label = SPACY_LABELS.get(ent.label_)
            if not label:
                continue
            context = text[max(0, ent.start_char - 60) : min(len(text), ent.end_char + 60)]
            entities.append(
                self._entity(
                    ent.text,
                    label,
                    ent.start_char,
                    ent.end_char,
                    0.82,
                    "spacy",
                    context,
                )
            )
        return entities

    def _extract_domain_terms(self, text: str) -> list[Entity]:
        """Extract curated domain entities and aliases from the local vocabulary."""
        candidates = []
        for alias, term in DOMAIN_LOOKUP.items():
            pattern = self._term_pattern(alias)
            for match in re.finditer(pattern, text, re.IGNORECASE):
                candidates.append(
                    (
                        match.start(),
                        match.end(),
                        term,
                    )
                )

        # Prefer the most specific phrase when aliases overlap, for example
        # "vector embeddings" should not also create a generic "Embedding" node.
        occupied: list[tuple[int, int]] = []
        entities = []
        for start, end, term in sorted(candidates, key=lambda item: (-(item[1] - item[0]), item[0])):
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            occupied.append((start, end))
            entities.append(
                self._entity(
                    term.canonical,
                    term.label,
                    start,
                    end,
                    term.confidence,
                    "domain",
                )
            )
        return entities

    def _extract_technical_terms(self, text: str) -> list[Entity]:
        """Backward-compatible wrapper for older tests/imports."""
        return self._extract_domain_terms(text)

    def _extract_with_llm(self, text: str) -> list[Entity]:
        """Optional LLM hook. Disabled by default and dependency-free."""
        if self.llm_enhancer is None or len(text.strip()) < 20:
            return []
        try:
            raw_items = self.llm_enhancer(text)
        except Exception:
            return []

        entities = []
        for item in raw_items:
            if isinstance(item, Entity):
                entities.append(item)
                continue
            if not isinstance(item, dict):
                continue
            entity_text = str(item.get("text") or item.get("name") or "").strip()
            label = str(item.get("label") or item.get("type") or "CONCEPT").upper()
            confidence = float(item.get("confidence", 0.74) or 0.74)
            if entity_text:
                entities.append(
                    self._entity(entity_text, label, 0, len(entity_text), confidence, "llm")
                )
        return entities

    def _extract_versions(self, text: str) -> list[Entity]:
        entities = []
        for match in re.finditer(r"\bv?\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?\b", text):
            entities.append(
                self._entity(match.group(0), "VERSION", match.start(), match.end(), 0.75, "rule")
            )
        return entities

    def _extract_repositories(self, text: str) -> list[Entity]:
        entities = []
        pattern = r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
        for match in re.finditer(pattern, text):
            repo = f"{match.group(1)}/{match.group(2).rstrip('/')}"
            entities.append(self._entity(repo, "REPOSITORY", match.start(), match.end(), 1.0, "rule"))
        return entities

    def _extract_from_headers(self, headers: Iterable[dict[str, Any]]) -> list[Entity]:
        entities = []
        for header in headers:
            text = str(header.get("text", "")).strip()
            if len(text) < 3:
                continue
            level = header.get("level", "?")
            entities.append(
                self._entity(
                    text,
                    "CONCEPT",
                    0,
                    len(text),
                    0.72,
                    "context",
                    context=f"Markdown heading level {level}",
                )
            )
        return entities

    def _extract_from_links(self, links: Iterable[dict[str, Any]]) -> list[Entity]:
        entities = []
        for link in links:
            text = str(link.get("text", "")).strip()
            url = str(link.get("url", ""))
            if not text:
                continue
            label = "REPOSITORY" if "github.com" in url else "RESOURCE"
            if ".org" in url or ".edu" in url:
                label = "ORGANIZATION"
            entities.append(
                self._entity(text, label, 0, len(text), 0.78, "context", context=f"Link: {url}")
            )
        return entities

    def _extract_from_code_blocks(self, code_blocks: Iterable[dict[str, Any]]) -> list[Entity]:
        entities = []
        for block in code_blocks:
            language = str(block.get("language", "")).strip()
            code = str(block.get("code", ""))
            if language:
                label = TECH_TERMS.get(language.lower(), "PROGRAMMING_LANGUAGE")
                entities.append(
                    self._entity(language, label, 0, len(language), 0.95, "context", "Code fence")
                )
            entities.extend(self._extract_imports_from_code(language, code))
        return entities

    def _extract_imports_from_code(self, language: str, code: str) -> list[Entity]:
        entities = []
        lower = language.lower()
        if lower == "python":
            pattern = r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))"
            for match in re.finditer(pattern, code, re.MULTILINE):
                module = (match.group(1) or match.group(2) or "").split(".")[0]
                if module:
                    entities.append(self._entity(module, "LIBRARY", 0, len(module), 0.9, "context"))
        elif lower in {"javascript", "typescript", "js", "ts"}:
            pattern = r"(?:from\s+['\"]([^'\"]+)['\"]|require\(\s*['\"]([^'\"]+)['\"]\s*\))"
            for match in re.finditer(pattern, code):
                module = self._normalize_js_module(match.group(1) or match.group(2) or "")
                if module:
                    entities.append(self._entity(module, "LIBRARY", 0, len(module), 0.9, "context"))
        return entities

    def _normalize_js_module(self, module: str) -> str:
        """Keep package dependencies, skip local implementation files."""
        if module.startswith((".", "/")):
            return ""
        parts = module.split("/")
        if module.startswith("@") and len(parts) >= 2:
            return "/".join(parts[:2])
        return parts[0]

    def _extract_pattern_relations(self, entities: list[Entity], text: str) -> list[EntityRelation]:
        # These patterns are deliberately conservative; the graph builder can
        # treat them as hints, not as final semantic truth.
        patterns = [
            (r"(.+?)\s+is\s+a\s+(.+?)(?:\.|,|$)", "IS_A"),
            (r"(.+?)\s+uses\s+(.+?)(?:\.|,|$)", "USES"),
            (r"(.+?)\s+developed\s+by\s+(.+?)(?:\.|,|$)", "DEVELOPED_BY"),
            (r"(.+?)\s+built\s+with\s+(.+?)(?:\.|,|$)", "BUILT_WITH"),
            (r"(.+?)\s+based\s+on\s+(.+?)(?:\.|,|$)", "BASED_ON"),
        ]
        relations = []
        for pattern, relation in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                source = self._find_entity_in_text(match.group(1), entities)
                target = self._find_entity_in_text(match.group(2), entities)
                if source and target and source.normalized != target.normalized:
                    relations.append(
                        EntityRelation(source.normalized, target.normalized, relation, 0.78)
                    )
        return relations

    def _extract_cooccurrence_relations(
        self, entities: list[Entity], text: str
    ) -> list[EntityRelation]:
        relations = []
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            sentence_entities = [
                entity
                for entity in entities
                if entity.text and entity.text.lower() in sentence.lower()
            ]
            for index, source in enumerate(sentence_entities):
                for target in sentence_entities[index + 1 :]:
                    if source.normalized != target.normalized:
                        relation_type = self._infer_type_pair_relation(source, target)
                        # Same-sentence type-pair relations are useful, but weak:
                        # they should add graph texture without pretending to be
                        # a fully parsed semantic claim.
                        relations.append(
                            EntityRelation(source.normalized, target.normalized, relation_type, 0.52)
                        )
        return relations

    def _infer_type_pair_relation(self, source: Entity, target: Entity) -> str:
        """Infer a low-confidence relation from entity type pairs."""
        return TYPE_PAIR_RELATIONS.get((source.label, target.label), "RELATED_TO")

    def _deduplicate(self, entities: Iterable[Entity]) -> list[Entity]:
        grouped: dict[str, Entity] = {}
        for entity in entities:
            entity = self._canonicalize_entity(entity)
            if self._is_low_value_entity(entity):
                continue
            key = entity.normalized or self._normalize(entity.text)
            current = grouped.get(key)
            if current is None or self._is_better_entity(entity, current):
                grouped[key] = entity
            elif current.source != entity.source:
                # Seeing the same entity through multiple paths is a small
                # confidence boost, but not enough to make weak matches certain.
                current.confidence = min(1.0, current.confidence + 0.05)
        merged = self._merge_semantic_duplicates(grouped.values())
        return sorted(merged, key=lambda item: (-item.confidence, item.label, item.text))

    def _is_better_entity(self, candidate: Entity, current: Entity) -> bool:
        """Choose the display label that gives the graph the clearest node type."""
        if candidate.confidence != current.confidence:
            return candidate.confidence > current.confidence
        return LABEL_PRIORITY.get(candidate.label, 0) > LABEL_PRIORITY.get(current.label, 0)

    def _canonicalize_entity(self, entity: Entity) -> Entity:
        term = DOMAIN_LOOKUP.get((entity.normalized or entity.text).lower())
        if not term:
            return entity
        return Entity(
            text=term.canonical,
            label=term.label,
            start=entity.start,
            end=entity.end,
            confidence=max(entity.confidence, term.confidence),
            source=entity.source,
            context=entity.context,
            normalized=term.canonical,
        )

    def _is_low_value_entity(self, entity: Entity) -> bool:
        text = (entity.normalized or entity.text).strip()
        lowered = text.lower()
        if entity.confidence < self.min_confidence:
            return True
        if self._domain_relevance_score(entity) < 0.55:
            return True
        if not text or lowered in STOP_CONCEPTS or self._is_noise_entity(text):
            return True
        if entity.label == "LOCATION" and entity.source == "spacy":
            return not self._has_geography_context(entity.context)
        if entity.label == "CONCEPT" and entity.source in {"context", "parser", "symbol"}:
            is_domain_concept = lowered in {term for term, label in TECH_TERMS.items() if label == "CONCEPT"}
            is_multi_word = len(text.split()) > 1
            return not (is_domain_concept or is_multi_word)
        if entity.label in {"FUNCTION", "CLASS"}:
            return len(text) < 3 or lowered in STOP_CONCEPTS
        return False

    def _domain_relevance_score(self, entity: Entity) -> float:
        """Keep the graph focused on technical/domain signal, not every NER hit."""
        text = (entity.normalized or entity.text).strip()
        lowered = text.lower()
        if lowered in DOMAIN_LOOKUP or lowered in TECH_TERMS:
            return 1.0
        if entity.label in DOMAIN_RELEVANT_LABELS:
            return max(0.72, entity.confidence)
        if entity.label in {"PERSON", "ORGANIZATION", "PRODUCT"}:
            return 0.68 if self._has_domain_context(entity.context) else 0.46
        if entity.label == "LOCATION":
            return 0.66 if self._has_geography_context(entity.context) else 0.32
        if entity.label in {"DATE", "TIME", "VERSION"}:
            return 0.24
        return entity.confidence * 0.65

    def _has_domain_context(self, context: str) -> bool:
        lowered = context.lower()
        return any(re.search(self._term_pattern(alias), lowered, re.IGNORECASE) for alias in DOMAIN_LOOKUP) or any(
            re.search(self._term_pattern(term), lowered, re.IGNORECASE) for term in TECH_TERMS
        )

    def _has_geography_context(self, context: str) -> bool:
        lowered = context.lower()
        return any(word in lowered for word in GEOGRAPHY_CONTEXT_WORDS)

    def _is_noise_entity(self, text: str) -> bool:
        """Filter parser/spaCy fragments that make the graph look random."""
        clean = " ".join(text.strip().split())
        lowered = clean.lower()
        possessive_base = lowered[:-2] if lowered.endswith("'s") else lowered
        if possessive_base in GENERIC_SINGLE_WORDS:
            return True
        if lowered.endswith("'s") and len(clean.split()) <= 3:
            return True
        if any(pattern.match(lowered) for pattern in NOISE_PATTERNS):
            return True
        if lowered.replace(".", "").replace("-", "").isdigit():
            return True
        special = sum(1 for char in clean if not char.isalnum() and char not in " _-.")
        return bool(clean) and special > len(clean) * 0.3

    def _merge_semantic_duplicates(self, entities: Iterable[Entity]) -> list[Entity]:
        """Merge aliases and optional embedding-near duplicates before graph insert."""
        merged: list[Entity] = []
        for entity in entities:
            match_index = next(
                (
                    index
                    for index, current in enumerate(merged)
                    if self._are_semantically_same(current, entity)
                ),
                None,
            )
            if match_index is None:
                merged.append(entity)
                continue
            current = merged[match_index]
            winner = entity if self._is_better_entity(entity, current) else current
            winner.confidence = min(1.0, max(current.confidence, entity.confidence) + 0.04)
            merged[match_index] = winner
        return merged

    def _are_semantically_same(self, left: Entity, right: Entity) -> bool:
        left_text = (left.normalized or left.text).strip()
        right_text = (right.normalized or right.text).strip()
        if left_text.lower() == right_text.lower():
            return True
        if self._acronym(left_text) == right_text.lower() or self._acronym(right_text) == left_text.lower():
            return True
        if self.semantic_similarity is None:
            return False
        try:
            return self.semantic_similarity(left_text, right_text) >= self.semantic_merge_threshold
        except Exception:
            return False

    def _acronym(self, text: str) -> str:
        words = [word for word in re.split(r"[^A-Za-z0-9]+", text) if word]
        if len(words) < 2:
            return ""
        return "".join(word[0].lower() for word in words)

    def _deduplicate_relations(self, relations: Iterable[EntityRelation]) -> list[EntityRelation]:
        best: dict[tuple[str, str, str], EntityRelation] = {}
        for relation in relations:
            key = (relation.source, relation.target, relation.relation)
            current = best.get(key)
            if current is None or relation.confidence > current.confidence:
                best[key] = relation
        return sorted(best.values(), key=lambda item: (-item.confidence, item.relation))

    def _find_entity_in_text(self, text: str, entities: list[Entity]) -> Optional[Entity]:
        haystack = text.lower()
        matches = [entity for entity in entities if entity.text.lower() in haystack]
        if not matches:
            return None
        return max(matches, key=lambda entity: len(entity.text))

    def _entity(
        self,
        text: str,
        label: str,
        start: int,
        end: int,
        confidence: float,
        source: str,
        context: str = "",
    ) -> Entity:
        clean = " ".join(text.strip().split())
        domain_term = DOMAIN_LOOKUP.get(clean.lower())
        display = domain_term.canonical if domain_term else CANONICAL_TERMS.get(clean.lower(), clean)
        return Entity(
            text=display,
            label=domain_term.label if domain_term else label,
            start=start,
            end=end,
            confidence=max(confidence, domain_term.confidence) if domain_term else confidence,
            source=source,
            context=context,
            normalized=self._normalize(display),
        )

    def _term_pattern(self, term: str) -> str:
        if re.search(r"\W", term):
            return rf"(?<!\w){re.escape(term)}(?!\w)"
        return rf"\b{re.escape(term)}\b"

    def _normalize(self, text: str) -> str:
        compact = " ".join(text.split()).strip()
        domain_term = DOMAIN_LOOKUP.get(compact.lower())
        return domain_term.canonical if domain_term else CANONICAL_TERMS.get(compact.lower(), compact)


entity_extractor = EntityExtractor()


def split_identifier(value: str) -> list[str]:
    """Split code-ish identifiers into readable concept words."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value.strip("_"))
    parts = re.split(r"[^A-Za-z0-9]+", spaced)
    return [part for part in parts if part]
