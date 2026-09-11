"""Deterministic normalization for local terminology matching."""

from __future__ import annotations

import re
import unicodedata


_WHITESPACE = re.compile(r"\s+")
_DASHES = "‐‑‒–—―﹘﹣－"
_APOSTROPHES = "‘’‚‛＇´`"
_PUNCTUATION = str.maketrans(
    {character: "-" for character in _DASHES}
    | {character: "'" for character in _APOSTROPHES}
)


def normalize_terminology_text(value: object) -> str:
    """Normalize a term without guessing language or correcting spelling."""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.translate(_PUNCTUATION)
    normalized = _WHITESPACE.sub(" ", normalized).strip()
    normalized = normalized.strip(".,;:!?！？。，、()[]{}\"'")
    return normalized.casefold()


def normalize_match_text(value: object) -> str:
    """Normalize a full question while preserving internal punctuation."""
    normalized, _spans = normalize_match_text_with_spans(value)
    return normalized


def normalize_match_text_with_spans(
    value: object,
) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Normalize text and retain source spans for user-facing match labels."""
    original = str(value or "")
    transformed: list[tuple[str, int, int]] = []
    for index, character in enumerate(original):
        value_for_character = (
            unicodedata.normalize("NFKC", character)
            .translate(_PUNCTUATION)
            .casefold()
        )
        transformed.extend(
            (item, index, index + 1) for item in value_for_character
        )

    collapsed: list[tuple[str, int, int]] = []
    for character, start, end in transformed:
        if character.isspace():
            if not collapsed or collapsed[-1][0] == " ":
                continue
            collapsed.append((" ", start, end))
        else:
            collapsed.append((character, start, end))

    while collapsed and collapsed[0][0] == " ":
        collapsed.pop(0)
    while collapsed and collapsed[-1][0] == " ":
        collapsed.pop()

    return (
        "".join(item[0] for item in collapsed),
        tuple((item[1], item[2]) for item in collapsed),
    )
