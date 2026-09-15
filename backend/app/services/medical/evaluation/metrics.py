"""Pure metric functions used by the offline medical evaluation runner."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Return precision in the first k rows, with a stable empty convention."""
    limit = max(0, int(k))
    rows = list(retrieved[:limit])
    if not rows:
        return 1.0 if not set(relevant) else 0.0
    relevant_set = set(relevant)
    return round(sum(item in relevant_set for item in rows) / len(rows), 4)


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Return recall in the first k rows without dividing by zero."""
    relevant_set = set(relevant)
    if not relevant_set:
        return 1.0 if not retrieved[: max(0, int(k))] else 0.0
    rows = set(retrieved[: max(0, int(k))])
    return round(len(rows & relevant_set) / len(relevant_set), 4)


def mean_reciprocal_rank(
    retrieved_rows: Iterable[Sequence[str]],
    relevant_rows: Iterable[Iterable[str]],
) -> float:
    """Calculate MRR over rows with first relevant result at rank one."""
    reciprocal_ranks: list[float] = []
    for retrieved, relevant in zip(retrieved_rows, relevant_rows):
        relevant_set = set(relevant)
        rank = next(
            (index for index, item in enumerate(retrieved, start=1) if item in relevant_set),
            None,
        )
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    if not reciprocal_ranks:
        return 0.0
    return round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4)


def accuracy(actual: Iterable[bool]) -> float:
    """Return the fraction of correct boolean checks."""
    values = list(actual)
    return round(sum(bool(value) for value in values) / len(values), 4) if values else 0.0


def rate(numerator: int, denominator: int) -> float:
    """Return a rounded rate with an explicit zero-denominator convention."""
    if denominator <= 0:
        return 0.0
    return round(max(0, int(numerator)) / denominator, 4)


def stable_unique(values: Iterable[str]) -> list[str]:
    """Preserve first-seen order while removing duplicate metric identifiers."""
    return list(dict.fromkeys(str(value) for value in values if str(value)))
