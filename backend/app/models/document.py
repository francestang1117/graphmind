"""Document metadata and in-memory registry."""

from dataclasses import dataclass, field
import datetime
from enum import Enum
from typing import Optional


class DocStatus(str, Enum):
    UPLOADED   = "uploaded"
    PROCESSING = "processing"
    DONE       = "done"
    FAILED     = "failed"

@dataclass
class Document:
    id:                str
    original_filename: str
    stored_filename:   str
    file_path:         str
    file_size:         int
    file_extension:    str
    file_hash:         str
    mime_type:         Optional[str]
    status:            DocStatus = DocStatus.UPLOADED
    error_message:     Optional[str] = None
    entity_count:      int = 0
    relation_count:    int = 0
    chunk_count:       int = 0
    uploaded_at:       str = field(
        default_factory=lambda: datetime.now(datetime.timezone.utc).isoformat()
    )
    processed_at:      Optional[str] = None

    def mark_processing(self):
        if self.status not in (DocStatus.UPLOADED, DocStatus.FAILED):
            raise ValueError(f"Cannot start processing from state '{self.status}'")
        self.status = DocStatus.PROCESSING

    def mark_done(self, entity_count: int, relation_count: int, chunk_count: int):
        self.status         = DocStatus.DONE
        self.entity_count   = entity_count
        self.relation_count = relation_count
        self.chunk_count    = chunk_count
        self.processed_at   = datetime.now(datetime.timezone.utc).isoformat()
        self.error_message  = None

    def mark_failed(self, reason: str):
        self.status        = DocStatus.FAILED
        self.error_message = reason

    def to_dict(self) -> dict:
        return {
            "id":                self.id,
            "original_filename": self.original_filename,
            "stored_filename":   self.stored_filename,
            "file_size":         self.file_size,
            "file_extension":    self.file_extension,
            "file_hash":         self.file_hash,
            "mime_type":         self.mime_type,
            "status":            self.status.value,
            "error_message":     self.error_message,
            "entity_count":      self.entity_count,
            "relation_count":    self.relation_count,
            "chunk_count":       self.chunk_count,
            "uploaded_at":       self.uploaded_at,
            "processed_at":      self.processed_at,
        }


class DocumentStore:
    """Thread-safe in-memory document registry."""

    def __init__(self):
        self._docs: dict[str, Document] = {}

    def save(self, doc: Document) -> Document:
        self._docs[doc.id] = doc
        return doc

    def get(self, doc_id: str) -> Optional[Document]:
        return self._docs.get(doc_id)

    def get_by_hash(self, file_hash: str) -> Optional[Document]:
        for doc in self._docs.values():
            if doc.file_hash == file_hash:
                return doc
        return None

    def list(self, limit: int = 50, offset: int = 0) -> list[Document]:
        docs = sorted(self._docs.values(), key=lambda d: d.uploaded_at, reverse=True)
        return docs[offset: offset + limit]

    def delete(self, doc_id: str) -> bool:
        return bool(self._docs.pop(doc_id, None))

    def total(self) -> int:
        return len(self._docs)


document_store = DocumentStore()
