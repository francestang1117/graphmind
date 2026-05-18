"""One document through parse, entities, graph, and search indexing."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import inspect
import logging
import time
from typing import Any, Callable, Optional

from app.services.entity_extractor import EntityExtractor, entity_extractor
from app.services.graph_builder_enhanced import KnowledgeGraph, knowledge_graph
from app.services.vector_store import VectorStore, vector_store
from app.core.metrics import record_pipeline


log = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int], Any]


class PipelineError(RuntimeError):
    """Raised when one document cannot finish the processing pipeline."""


@dataclass
class PipelineResult:
    filename: str
    original_filename: str
    title: str
    format: str
    chunks_count: int
    entities_count: int
    relations_count: int
    indexed_chunks: int
    graph_nodes: int
    graph_edges: int
    time_seconds: float
    status: str = "indexed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProcessingPipeline:
    """Runs the current MVP processing path for one stored document."""

    def __init__(
        self,
        extractor: EntityExtractor = entity_extractor,
        graph: KnowledgeGraph = knowledge_graph,
        store: VectorStore = vector_store,
    ) -> None:
        self.extractor = extractor
        self.graph = graph
        self.store = store

    def process(
        self,
        file_path: str,
        filename: str,
        original_filename: str = "",
        on_progress: Optional[ProgressCallback] = None,
    ) -> dict[str, Any]:
        """Process a stored file and return a compact summary.

        The parser already writes the parsed pieces to storage. This layer is
        the extra pass that makes the current graph/search screens feel live.
        """
        started_at = time.time()
        display_name = original_filename or filename

        try:
            self._progress(on_progress, "Parsing document", 15)
            parsed = self._parse_document(filename, file_path, original_filename)

            self._progress(on_progress, "Extracting entities", 40)
            entities = self.extractor.extract_from_parsed_document(parsed)

            self._progress(on_progress, "Finding relationships", 60)
            relations = self.extractor.extract_relations(entities, parsed.get("content", ""))

            self._progress(on_progress, "Updating graph", 75)
            # The graph is still session-local, so upload/reindex needs to feed
            # it right away instead of waiting for a future persistent graph DB.
            self.graph.add_document(display_name, entities, relations, document_id=f"doc:{filename}")
            graph_stats = self.graph.get_stats()

            self._progress(on_progress, "Indexing chunks", 90)
            # Search uses the same chunks the parser saved. Indexing here keeps
            # a fresh upload searchable before the user refreshes the page.
            indexed_chunks = self.store.add_chunks(parsed.get("chunks", []), display_name)

            self._progress(on_progress, "Done", 100)
            result = PipelineResult(
                filename=filename,
                original_filename=display_name,
                title=str(parsed.get("metadata", {}).get("title") or display_name),
                format=str(parsed.get("metadata", {}).get("format") or ""),
                chunks_count=len(parsed.get("chunks", [])),
                entities_count=len(entities),
                relations_count=len(relations),
                indexed_chunks=indexed_chunks,
                graph_nodes=int(graph_stats.get("total_nodes", 0)),
                graph_edges=int(graph_stats.get("total_edges", 0)),
                time_seconds=round(time.time() - started_at, 2),
            )
            record_pipeline("indexed", result.format, result.time_seconds)
            log.info(
                "Processed %s: %d chunks, %d entities, %d relations",
                display_name,
                result.chunks_count,
                result.entities_count,
                result.relations_count,
            )
            return result.to_dict()
        except Exception as exc:
            log.exception("Document processing failed for %s", display_name)
            self._progress(on_progress, "Failed", 100)
            record_pipeline("failed", "", time.time() - started_at)
            raise PipelineError(f"Could not process {display_name}: {exc}") from exc

    def _progress(self, callback: Optional[ProgressCallback], step: str, pct: int) -> None:
        if not callback:
            return
        result = callback(step, pct)
        # The current upload path is sync. If a future worker passes an async
        # callback by mistake, log it instead of pretending progress was sent.
        if inspect.isawaitable(result):
            log.debug("Ignoring awaitable pipeline progress callback for step %s", step)

    def _parse_document(
        self,
        filename: str,
        file_path: str,
        original_filename: str,
    ) -> dict[str, Any]:
        # This helper still lives next to the document routes. Lazy import keeps
        # the service callable from the routes without tying the files in a knot.
        from app.api.endpoints.documents_with_markdown import parse_document_file

        return parse_document_file(filename, file_path, original_filename)


def process_uploaded_document(
    filename: str,
    file_path: str,
    original_filename: str = "",
) -> dict[str, Any]:
    """Background-task friendly wrapper used after upload."""
    return pipeline.process(file_path, filename, original_filename)


pipeline = ProcessingPipeline()
