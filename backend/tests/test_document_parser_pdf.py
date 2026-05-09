"""PDF parser tests."""

import sys
from types import SimpleNamespace

from app.services.document_parser import PDFParser


class FakePDF:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakePDFPage:
    def __init__(self, text, tables=None, words=None):
        self._text = text
        self._tables = tables or []
        self._words = words or []

    def extract_text(self):
        return self._text

    def extract_tables(self):
        return self._tables

    def extract_words(self, extra_attrs=None):
        return self._words


def test_pdfplumber_parser_extracts_pages_and_tables(tmp_path, monkeypatch):
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    page = FakePDFPage(
        "Revenue report\nTotal revenue increased.",
        tables=[
            [
                ["Metric", "Value"],
                ["Revenue", "$10"],
                ["", ""],
            ]
        ],
        words=[
            {"text": "Revenue", "size": 18},
            {"text": "report", "size": 18},
            {"text": "Total", "size": 10},
        ],
    )

    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert parsed.metadata["parser"] == "pdfplumber"
    assert parsed.metadata["pages"] == 1
    assert parsed.metadata["table_count"] == 1
    assert parsed.sections[0].title == "Page 1"
    assert parsed.tables[0].headers == ["Metric", "Value"]
    assert parsed.tables[0].rows == [["Revenue", "$10"]]
    assert any(chunk["type"] == "page" and chunk["page"] == 1 for chunk in parsed.chunks)
    assert any(chunk["type"] == "table" and "Revenue | $10" in chunk["text"] for chunk in parsed.chunks)


def test_pdf_table_normalizer_skips_empty_tables():
    parser = PDFParser()

    assert parser._normalise_table([]) == ([], [])
    assert parser._normalise_table([["", ""], ["", None]]) == ([], [])
