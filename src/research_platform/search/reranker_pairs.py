"""Versioned, source-preserving query/evidence pairs for cross-encoders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from research_platform.search.contracts import EvidenceHit

RERANKER_PAIR_FORMAT_ID = "query-source-chunk-v1"
DEFAULT_MAX_PAIR_TOKENS = 512


class PairTokenCounter(Protocol):
    """Count a complete query/evidence pair, including model special tokens."""

    def count_pair(self, query: str, evidence_text: str) -> int:
        """Return the untruncated token count for the model's paired input."""


class RerankerPairFormatError(ValueError):
    """A query, candidate, or tokenizer count cannot form a valid pair."""


@dataclass(frozen=True)
class PairBudgetViolation:
    """One candidate whose complete pair exceeds at least one tokenizer budget."""

    chunk_id: str
    token_counts: tuple[tuple[str, int], ...]
    maximum_pair_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, str) or not self.chunk_id.strip():
            raise ValueError("chunk_id must be non-empty")
        if not isinstance(self.token_counts, tuple) or not self.token_counts:
            raise ValueError("token_counts must contain tokenizer measurements")
        if (
            isinstance(self.maximum_pair_tokens, bool)
            or not isinstance(self.maximum_pair_tokens, int)
            or self.maximum_pair_tokens <= 0
        ):
            raise ValueError("maximum_pair_tokens must be a positive integer")
        names: list[str] = []
        counts: list[int] = []
        for item in self.token_counts:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("token counts must be tokenizer/count pairs")
            name, count = item
            if not isinstance(name, str) or not name.strip():
                raise ValueError("tokenizer identifiers must be non-empty")
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise ValueError("token counts must be positive integers")
            names.append(name)
            counts.append(count)
        if len(set(names)) != len(names):
            raise ValueError("tokenizer identifiers must be unique")
        if not any(count > self.maximum_pair_tokens for count in counts):
            raise ValueError(
                "at least one token count must exceed the configured budget"
            )


@dataclass(frozen=True)
class RerankerPair:
    """An unchanged query/source-chunk pair that retains its full evidence hit."""

    evidence_hit: EvidenceHit
    query: str
    token_counts: tuple[tuple[str, int], ...]
    maximum_pair_tokens: int
    pair_format_id: str = RERANKER_PAIR_FORMAT_ID

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_hit, EvidenceHit):
            raise ValueError("evidence_hit must be an EvidenceHit")
        if (
            not isinstance(self.evidence_hit.text, str)
            or not self.evidence_hit.text.strip()
        ):
            raise ValueError("evidence hit must have non-empty evidence text")
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must be non-empty")
        if not isinstance(self.token_counts, tuple) or not self.token_counts:
            raise ValueError("token_counts must contain tokenizer measurements")
        if (
            isinstance(self.maximum_pair_tokens, bool)
            or not isinstance(self.maximum_pair_tokens, int)
            or self.maximum_pair_tokens <= 0
        ):
            raise ValueError("maximum_pair_tokens must be a positive integer")
        names: list[str] = []
        for item in self.token_counts:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("token counts must be tokenizer/count pairs")
            name, count = item
            if not isinstance(name, str) or not name.strip():
                raise ValueError("tokenizer identifiers must be non-empty")
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or not 1 <= count <= self.maximum_pair_tokens
            ):
                raise ValueError("pair token counts must be positive and within budget")
            names.append(name)
        if len(set(names)) != len(names):
            raise ValueError("tokenizer identifiers must be unique")
        if self.pair_format_id != RERANKER_PAIR_FORMAT_ID:
            raise ValueError("unsupported reranker pair format")


class RerankerPairBudgetExceeded(ValueError):
    """The full candidate set cannot fit without truncation under every tokenizer."""

    def __init__(self, violations: Sequence[PairBudgetViolation]) -> None:
        self.violations = tuple(violations)
        if not self.violations or any(
            not isinstance(item, PairBudgetViolation) for item in self.violations
        ):
            raise ValueError("violations must contain PairBudgetViolation values")
        super().__init__(
            "one or more complete query/evidence pairs exceed the configured token budget"
        )


def build_reranker_pairs(
    query: str,
    evidence_hits: Sequence[EvidenceHit],
    *,
    token_counters: Mapping[str, PairTokenCounter],
    maximum_pair_tokens: int = DEFAULT_MAX_PAIR_TOKENS,
) -> tuple[RerankerPair, ...]:
    """Build all candidate pairs unchanged or fail without returning a partial set.

    The query and each hit's stored text are passed verbatim to every counter.
    Counter identifiers should name the exact model/tokenizer revisions being
    compared. Each counter must count the complete paired input, including special
    tokens, with truncation disabled. If any pair exceeds the limit for any supplied
    tokenizer, the complete operation raises RerankerPairBudgetExceeded.
    """
    if not isinstance(query, str) or not query.strip():
        raise RerankerPairFormatError("query text must be non-empty")
    if (
        isinstance(maximum_pair_tokens, bool)
        or not isinstance(maximum_pair_tokens, int)
        or maximum_pair_tokens <= 0
    ):
        raise RerankerPairFormatError("maximum_pair_tokens must be a positive integer")
    if not isinstance(token_counters, Mapping) or not token_counters:
        raise RerankerPairFormatError("at least one tokenizer counter is required")

    counter_items = tuple(token_counters.items())
    for name, counter in counter_items:
        if not isinstance(name, str) or not name.strip():
            raise RerankerPairFormatError("tokenizer identifiers must be non-empty")
        if not callable(getattr(counter, "count_pair", None)):
            raise RerankerPairFormatError(
                "each tokenizer counter must implement count_pair"
            )
    counters = tuple(sorted(counter_items, key=lambda item: item[0]))

    hits = tuple(evidence_hits)
    if any(not isinstance(hit, EvidenceHit) for hit in hits):
        raise TypeError("evidence_hits must contain EvidenceHit values")
    chunk_ids = tuple(hit.chunk_id for hit in hits)
    ranks = tuple(hit.rank for hit in hits)
    if len(set(chunk_ids)) != len(chunk_ids):
        raise RerankerPairFormatError("candidate chunk IDs must be unique")
    if len(set(ranks)) != len(ranks):
        raise RerankerPairFormatError("candidate original ranks must be unique")

    pairs: list[RerankerPair] = []
    violations: list[PairBudgetViolation] = []
    for hit in hits:
        if not hit.text.strip():
            raise RerankerPairFormatError(
                f"candidate {hit.chunk_id} has empty evidence text"
            )
        lengths: list[tuple[str, int]] = []
        for name, counter in counters:
            count = counter.count_pair(query, hit.text)
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise RerankerPairFormatError(
                    f"tokenizer {name} returned an invalid pair length"
                )
            lengths.append((name, count))
        token_counts = tuple(lengths)
        if any(count > maximum_pair_tokens for _, count in token_counts):
            violations.append(
                PairBudgetViolation(
                    chunk_id=hit.chunk_id,
                    token_counts=token_counts,
                    maximum_pair_tokens=maximum_pair_tokens,
                )
            )
            continue
        pairs.append(
            RerankerPair(
                evidence_hit=hit,
                query=query,
                token_counts=token_counts,
                maximum_pair_tokens=maximum_pair_tokens,
            )
        )

    if violations:
        raise RerankerPairBudgetExceeded(violations)
    return tuple(pairs)
