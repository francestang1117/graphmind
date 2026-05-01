"""Question-answering engine for Module 6.

Implemented:
- rebuilds the current vector index before answering
- pulls lightweight graph context from uploaded documents
- keeps short in-memory conversation history
- returns citation sources from retrieved chunks
- uses an optional LLM client only when configured

The fallback answer is intentionally extractive. It lets the Chat API work in a
fresh local checkout without API keys, while keeping a clear upgrade path for
GPT/OpenAI-backed generation later.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import os
import re
from typing import Any, Dict, List, Optional


@dataclass
class QAResult:
    answer: str
    sources: list[dict[str, str]]
    conversation_id: Optional[str] = None
    mode: str = "local"


class QAEngine:
    """Answer questions from the current parsed document/search/graph state."""

    def __init__(self) -> None:
        self.conversations: Dict[str, List[Dict[str, str]]] = {}

    def answer(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return an answer with sources, using local retrieval when no LLM is configured."""
        context = self._get_vector_context(question, user_id)
        graph_context = self._get_graph_context(question, user_id)
        history = self._get_history(conversation_id)

        llm_answer = self._answer_with_optional_llm(question, context, graph_context, history)
        mode = "llm" if llm_answer else "local"
        answer_text = llm_answer or self._build_local_answer(question, context, graph_context, user_id)

        if conversation_id:
            self._save_to_history(conversation_id, question, answer_text)

        result = QAResult(
            answer=answer_text,
            sources=self._extract_sources(context),
            conversation_id=conversation_id,
            mode=mode,
        )
        return {
            "answer": result.answer,
            "sources": result.sources,
            "conversation_id": result.conversation_id,
            "mode": result.mode,
        }

    def _get_vector_context(self, question: str, user_id: Optional[str]) -> str:
        """Rebuild search from current uploads so chat does not depend on tab order."""
        try:
            from app.api.endpoints.search import rebuild_vector_index

            store = rebuild_vector_index(user_id)
            return store.get_context_for_qa(question, n_chunks=5)
        except Exception:
            return "No relevant context found."

    def _get_graph_context(self, question: str, user_id: Optional[str]) -> str:
        """Rebuild graph context from current uploads for a graph-augmented hint."""
        try:
            from app.api.endpoints.graph import rebuild_graph_from_documents

            graph = rebuild_graph_from_documents(user_id)
            nodes = graph.search_nodes(question, limit=5)
        except Exception:
            nodes = []

        if not nodes:
            return "No graph context available."

        parts = []
        for node in nodes:
            try:
                neighbors = graph.get_neighbors(node["id"], max_depth=1)
            except Exception:
                neighbors = []
            related = [item["node"]["label"] for item in neighbors[:3] if item.get("node")]
            line = f"- {node['label']} ({node['type']})"
            if related:
                line += f" -> related to: {', '.join(related)}"
            parts.append(line)
        return "\n".join(parts)

    def _answer_with_optional_llm(
        self,
        question: str,
        context: str,
        graph_context: str,
        history: list[dict[str, str]],
    ) -> Optional[str]:
        """Use a future OpenAI/GPT provider only when explicitly configured."""
        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL")
        if not api_key or not model:
            return None

        try:
            from openai import OpenAI
        except ImportError:
            return None

        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=self._build_system_prompt(context, graph_context),
            input=[*history, {"role": "user", "content": question}],
        )
        return getattr(response, "output_text", None)

    def _build_system_prompt(self, context: str, graph_context: str) -> str:
        return f"""You answer questions using the user's uploaded documents.

If the answer is not supported by the retrieved context, say that clearly.
Keep the answer concise and cite the source documents.

## Retrieved Context
{context}

## Knowledge Graph Context
{graph_context}

Respond in the same language as the user's question."""

    def _build_local_answer(
        self,
        question: str,
        context: str,
        graph_context: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Readable extractive response used before an LLM key is configured."""
        snippets = self._parse_context_blocks(context)
        document_answer = self._build_named_document_answer(question, user_id)
        if document_answer:
            return document_answer

        if self._asks_for_collection_summary(question):
            return self._build_collection_summary(user_id)

        if self._asks_for_frameworks(question):
            framework_answer = self._build_framework_answer(graph_context, snippets)
            if framework_answer:
                return framework_answer

        if "No relevant context found." in context:
            return (
                "I couldn't find relevant context in the uploaded documents yet. "
                "Try uploading a document or asking with terms that appear in the files."
            )

        if self._asks_for_main_concepts(question):
            concepts = self._extract_local_concepts(snippets, graph_context)
            if concepts:
                lines = ["Main concepts I found:"]
                for concept, source in concepts[:8]:
                    lines.append(f"- {concept} ({source})")
            else:
                lines = ["I found relevant context, but not enough clear repeated concepts to summarize confidently."]
        else:
            lines = ["I found these relevant points:"]
            for source, body in snippets[:3]:
                lines.append(f"- {source}: {self._safe_excerpt(body)}")

        if graph_context != "No graph context available.":
            lines.append("")
            lines.append("Related graph context:")
            lines.append(graph_context)
        return "\n".join(lines)

    def _build_named_document_answer(self, question: str, user_id: Optional[str]) -> Optional[str]:
        """Answer questions that name a specific uploaded file/title."""
        if not self._asks_about_document_content(question):
            return None
        match = self._find_document_for_question(question, user_id)
        if not match:
            return None
        filename, parsed = match
        summary = self._summarize_single_document(filename, parsed)
        return f"Main content of {filename}:\n\n{summary}"

    def _asks_about_document_content(self, question: str) -> bool:
        lowered = question.lower()
        return any(
            phrase in lowered
            for phrase in (
                "main content",
                "what is in",
                "what's in",
                "tell me about",
                "summarize",
                "summary of",
                "内容",
                "总结",
            )
        )

    def _find_document_for_question(
        self,
        question: str,
        user_id: Optional[str],
    ) -> Optional[tuple[str, dict[str, Any]]]:
        try:
            from app.api.endpoints.documents_with_markdown import get_cached_parse, parse_document_file
            from app.services.document_service import document_service
        except Exception:
            return None

        query_tokens = self._content_tokens(question)
        best: tuple[int, str, dict[str, Any]] | None = None
        for metadata in document_service.list_documents(user_id):
            filename = metadata.get("filename", "")
            original = metadata.get("original_filename") or filename
            file_path = metadata.get("file_path", "")
            if not filename or not file_path:
                continue
            doc_tokens = self._content_tokens(original)
            score = len(query_tokens & doc_tokens)
            if score < 2:
                continue
            parsed = get_cached_parse(filename)
            if not parsed:
                try:
                    parsed = parse_document_file(filename, file_path, original)
                except Exception:
                    continue
            if best is None or score > best[0]:
                best = (score, original, parsed)
        if best is None:
            return None
        return best[1], best[2]

    def _content_tokens(self, value: str) -> set[str]:
        stop = {
            "about", "content", "design", "document", "file", "main", "summary",
            "summarize", "tell", "the", "what", "what's",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.lower())
            if len(token) > 2 and token not in stop
        }

    def _summarize_single_document(self, filename: str, parsed: dict[str, Any]) -> str:
        metadata = parsed.get("metadata", {})
        extra = parsed.get("extra", {})
        chunks = parsed.get("chunks", [])
        fmt = str(metadata.get("format") or "").upper() or "document"
        title = str(metadata.get("title") or filename)

        lines = [f"- Type: {fmt}", f"- Title: {title}"]
        terms = [
            str(item.get("text"))
            for item in extra.get("entities", [])
            if isinstance(item, dict) and item.get("text")
        ][:6]
        if terms:
            lines.append(f"- Key terms: {', '.join(terms)}")

        chunk_summaries = []
        for chunk in chunks:
            if not isinstance(chunk, dict) or not chunk.get("text"):
                continue
            text = str(chunk["text"])
            if len(text.split()) < 4:
                continue
            chunk_summaries.append(self._safe_excerpt(text, 220))
            if len(chunk_summaries) >= 3:
                break
        if chunk_summaries:
            lines.append("- Main points:")
            for item in chunk_summaries:
                lines.append(f"  - {item}")
        return "\n".join(lines)

    def _parse_context_blocks(self, context: str) -> list[tuple[str, str]]:
        snippets = []
        current_source = "Retrieved context"
        for block in context.split("\n\n---\n\n"):
            lines = [line for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            if lines[0].startswith("[From:"):
                current_source = self._source_label(lines[0])
                body = " ".join(lines[1:]).strip()
            else:
                body = " ".join(lines).strip()
            if body:
                snippets.append((current_source, body))
        return snippets

    def _asks_for_main_concepts(self, question: str) -> bool:
        lowered = question.lower()
        return any(phrase in lowered for phrase in ("main concept", "key concept", "主要概念", "核心概念"))

    def _asks_for_collection_summary(self, question: str) -> bool:
        lowered = question.lower()
        return (
            ("summarize" in lowered or "summary" in lowered or "总结" in lowered)
            and ("all file" in lowered or "all document" in lowered or "across" in lowered or "所有" in lowered)
        )

    def _build_collection_summary(self, user_id: Optional[str]) -> str:
        """Summarize each uploaded file from parser output, not search snippets."""
        try:
            from app.api.endpoints.documents_with_markdown import get_cached_parse, parse_document_file
            from app.services.document_service import document_service
        except Exception:
            return "I couldn't access the uploaded document list yet."

        summaries = []
        for metadata in document_service.list_documents(user_id):
            filename = metadata.get("filename", "")
            original = metadata.get("original_filename") or filename
            file_path = metadata.get("file_path", "")
            if not filename or not file_path:
                continue
            parsed = get_cached_parse(filename)
            if not parsed:
                try:
                    parsed = parse_document_file(filename, file_path, original)
                except Exception:
                    continue
            summary = self._summarize_parsed_document(original, parsed)
            if summary:
                summaries.append(summary)

        if not summaries:
            return "I couldn't find parsed document content to summarize yet. Try uploading or re-parsing files first."

        lines = ["Key ideas across your uploaded files:"]
        for item in summaries[:8]:
            lines.append(f"\n- {item}")
        return "\n".join(lines)

    def _summarize_parsed_document(self, filename: str, parsed: dict[str, Any]) -> str:
        metadata = parsed.get("metadata", {})
        extra = parsed.get("extra", {})
        fmt = str(metadata.get("format") or "").upper() or "document"
        title = str(metadata.get("title") or filename)
        chunks = parsed.get("chunks", [])
        entities = extra.get("entities", [])
        imports = extra.get("imports", [])
        functions = extra.get("functions", [])

        if imports or functions:
            bits = []
            if imports:
                bits.append(f"dependencies: {', '.join(map(str, imports[:4]))}")
            if functions:
                bits.append(f"functions: {', '.join(map(str, functions[:4]))}")
            return f"{filename}: {fmt} code file covering " + "; ".join(bits)

        if fmt in {"JSON", "CSV"}:
            chunks_text = " ".join(str(chunk.get("text", "")) for chunk in chunks[:2] if isinstance(chunk, dict))
            fields = self._extract_structured_fields(chunks_text)
            if fields:
                return f"{filename}: {fmt} data/metadata with fields such as {', '.join(fields[:6])}"
            return f"{filename}: {fmt} structured data file"

        concept_names = [
            str(item.get("text"))
            for item in entities
            if isinstance(item, dict) and item.get("text")
        ][:5]
        first_text = ""
        for chunk in chunks:
            if isinstance(chunk, dict) and chunk.get("text"):
                first_text = self._safe_excerpt(str(chunk["text"]), 170)
                break
        if concept_names:
            return f"{filename}: {title}; key terms include {', '.join(concept_names)}"
        if first_text:
            return f"{filename}: {first_text}"
        return f"{filename}: parsed {fmt.lower()} document"

    def _extract_structured_fields(self, text: str) -> list[str]:
        fields = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*:", text)
        ignored = {"array", "false", "http", "https", "object", "true", "with"}
        result = []
        for field in fields:
            if field.lower() in ignored or field in result:
                continue
            result.append(field)
        return result

    def _asks_for_frameworks(self, question: str) -> bool:
        lowered = question.lower()
        return "framework" in lowered or "library" in lowered or "libraries" in lowered or "框架" in lowered

    def _build_framework_answer(
        self,
        graph_context: str,
        snippets: list[tuple[str, str]],
    ) -> Optional[str]:
        """Answer framework-frequency questions from graph/entity signals first."""
        counts: Counter[str] = Counter()
        sources: dict[str, set[str]] = {}
        for label, entity_type, source in self._graph_entities(graph_context):
            if entity_type not in {"FRAMEWORK", "LIBRARY", "TOOL", "DATABASE"}:
                continue
            counts[label] += 3
            sources.setdefault(label, set()).add(source)

        known = {
            "Angular", "ChromaDB", "Django", "Docker", "FastAPI", "Flask",
            "Keras", "Lodash", "Neo4j", "Node.js", "NumPy", "pandas",
            "PostgreSQL", "PyTorch", "React", "Redis", "TensorFlow", "Vue",
        }
        for source, body in snippets:
            lowered = body.lower()
            for name in known:
                if re.search(rf"\b{re.escape(name.lower())}\b", lowered):
                    counts[name] += 1
                    sources.setdefault(name, set()).add(source)

        if not counts:
            return None

        lines = ["Frameworks and libraries I found most often:"]
        for name, count in counts.most_common(8):
            source_list = ", ".join(sorted(sources.get(name, {"context"})))
            lines.append(f"- {name}: {count} signal{'s' if count != 1 else ''} ({source_list})")
        return "\n".join(lines)

    def _graph_entities(self, graph_context: str) -> list[tuple[str, str, str]]:
        entities = []
        for line in graph_context.splitlines():
            match = re.match(r"-\s+(.+?)\s+\(([^)]+)\)", line.strip())
            if match:
                entities.append((match.group(1).strip(), match.group(2).strip().upper(), "graph"))
        return entities

    def _extract_local_concepts(
        self,
        snippets: list[tuple[str, str]],
        graph_context: str,
    ) -> list[tuple[str, str]]:
        """Extract a compact concept list from graph labels and retrieved text."""
        candidates: list[tuple[str, str]] = []
        for line in graph_context.splitlines():
            match = re.match(r"-\s+(.+?)\s+\(([^)]+)\)", line.strip())
            if match:
                candidates.append((match.group(1).strip(), "graph"))

        stop_words = {
            "about", "after", "assignment", "before", "class", "could", "different",
            "document", "documents", "first", "ideas", "individual", "issue", "main",
            "method", "notes", "parts", "question", "relevant", "should", "these",
            "using", "what", "when", "which", "with", "your",
        }
        counts: Counter[str] = Counter()
        sources: dict[str, str] = {}
        for source, body in snippets:
            for phrase in re.findall(r"\b[A-Z][A-Za-z0-9+#.-]*(?:\s+[A-Z][A-Za-z0-9+#.-]*){0,3}\b", body):
                cleaned = phrase.strip(" .,:;()[]")
                if len(cleaned) < 3 or cleaned.lower() in stop_words:
                    continue
                counts[cleaned] += 2
                sources.setdefault(cleaned, source)
            for word in re.findall(r"\b[a-z][a-z0-9+#.-]{4,}\b", body.lower()):
                if word in stop_words:
                    continue
                counts[word.title()] += 1
                sources.setdefault(word.title(), source)

        for concept, source in candidates:
            counts[concept] += 4
            sources.setdefault(concept, source)

        concepts: list[tuple[str, str]] = []
        for concept, _ in counts.most_common(20):
            if any(self._is_redundant_concept(concept, existing) for existing, _ in concepts):
                continue
            concepts.append((concept, sources.get(concept, "context")))
            if len(concepts) >= 12:
                break
        return concepts

    def _is_redundant_concept(self, candidate: str, existing: str) -> bool:
        left = candidate.lower()
        right = existing.lower()
        return left == right or (len(left) > 3 and left in right.split()) or (len(left) > 3 and left in right)

    def _safe_excerpt(self, text: str, max_len: int = 260) -> str:
        clean = " ".join(text.split())
        if len(clean) <= max_len:
            return clean
        boundary = max(clean.rfind(".", 0, max_len), clean.rfind(";", 0, max_len), clean.rfind(",", 0, max_len))
        if boundary < max_len * 0.55:
            boundary = clean.rfind(" ", 0, max_len)
        if boundary < 80:
            boundary = max_len
        return clean[:boundary].rstrip(" ,;:") + "..."

    def _source_label(self, source_line: str) -> str:
        if not source_line.startswith("[From:"):
            return "Retrieved context"
        return source_line.split("From:", 1)[1].split("|", 1)[0].strip()

    def _get_history(self, conversation_id: Optional[str]) -> list[dict[str, str]]:
        if not conversation_id:
            return []
        return self.conversations.get(conversation_id, [])[-6:]

    def _save_to_history(self, conversation_id: str, question: str, answer: str) -> None:
        self.conversations.setdefault(conversation_id, []).extend(
            [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
        )

    def _extract_sources(self, context: str) -> list[dict[str, str]]:
        """Extract source documents from vector context blocks."""
        sources = []
        for line in context.splitlines():
            if not line.startswith("[From:"):
                continue
            try:
                doc = line.split("From:", 1)[1].split("|", 1)[0].strip()
                score = line.split("Relevance:", 1)[1].split("]", 1)[0].strip()
            except Exception:
                continue
            sources.append({"document": doc, "relevance": score})

        unique = []
        seen = set()
        for source in sources:
            if source["document"] in seen:
                continue
            seen.add(source["document"])
            unique.append(source)
        return unique


qa_engine = QAEngine()
