"""Evidence references and bounded prompt packing for research runs."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from research_platform.tools.research_tools import CollectedEvidence


class EvidenceRef(BaseModel):
    """Stable run-scoped handle for one retrieved passage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handle: str = Field(pattern=r"^E[1-9][0-9]*$")
    chunk_id: str
    paper_id: str
    title: str | None
    publication_year: int | None
    kind: str


class EvidenceRegistry(BaseModel):
    """Immutable evidence registry stored in graph state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    refs: tuple[EvidenceRef, ...] = ()
    dropped: int = Field(default=0, ge=0)

    def register(
        self, items: Sequence[CollectedEvidence], *, max_passages: int
    ) -> tuple[EvidenceRegistry, tuple[EvidenceRef, ...]]:
        """Return a registry extended with unseen passages up to the configured cap."""
        if max_passages < 0:
            raise ValueError("max_passages must be non-negative")

        seen_chunks = {ref.chunk_id for ref in self.refs}
        refs = list(self.refs)
        added: list[EvidenceRef] = []
        dropped = self.dropped
        for item in items:
            if item.chunk_id in seen_chunks:
                continue
            if len(refs) >= max_passages:
                dropped += 1
                continue
            seen_chunks.add(item.chunk_id)

            ref = EvidenceRef(
                handle=f"E{len(refs) + 1}",
                chunk_id=item.chunk_id,
                paper_id=item.paper_id,
                title=item.title,
                publication_year=item.publication_year,
                kind=item.kind,
            )
            refs.append(ref)
            added.append(ref)

        return EvidenceRegistry(refs=tuple(refs), dropped=dropped), tuple(added)

    def resolve(self, handle: str) -> EvidenceRef | None:
        """Find the registered reference for a handle."""
        return next((ref for ref in self.refs if ref.handle == handle), None)

    def handles(self) -> frozenset[str]:
        """Return the handles currently registered."""
        return frozenset(ref.handle for ref in self.refs)


_TABLE_KINDS = frozenset({"table", "table_row_group"})


def approx_tokens(text: str) -> int:
    """Estimate tokens using the Phase 3 character-count approximation."""
    return math.ceil(len(text) / 4)


@dataclass(frozen=True)
class PackedEvidence:
    """Rendered evidence text and the handles included or omitted by the cap."""

    text: str
    included: tuple[str, ...]
    omitted: tuple[str, ...]


def pack_evidence(
    refs: Sequence[EvidenceRef],
    texts: Mapping[str, str],
    *,
    max_tokens: int,
    max_passage_chars: int = 2000,
    max_table_chars: int = 8000,
) -> PackedEvidence:
    """Pack source passages in order without exceeding the approximate token cap.

    Prose passages are cut at ``max_passage_chars``. Labeled table rows are longer
    than prose and are cut only at ``max_table_chars``, so a row and its headers stay
    together.
    """
    if max_tokens < 0:
        raise ValueError("max_tokens must be non-negative")
    if max_passage_chars < 1 or max_table_chars < 1:
        raise ValueError("max_passage_chars and max_table_chars must be positive")

    blocks: list[str] = []
    included: list[str] = []
    omitted: list[str] = []
    budget_exhausted = False
    for ref in refs:
        if budget_exhausted:
            omitted.append(ref.handle)
            continue
        raw_text = neutralize(texts.get(ref.chunk_id, ""))
        limit = max_table_chars if ref.kind in _TABLE_KINDS else max_passage_chars
        passage = raw_text
        if len(raw_text) > limit:
            passage = raw_text[:limit] + "…"

        paper_id = neutralize(ref.paper_id).replace('"', "'")
        attributes = [f'handle="{ref.handle}"', f'paper="{paper_id}"']
        if ref.kind == "abstract":
            attributes.append('kind="abstract"')
        if ref.publication_year is not None:
            attributes.append(f'year="{ref.publication_year}"')
        if ref.title is not None:
            title = neutralize(ref.title).replace('"', "'")
            attributes.append(f'title="{title}"')
        block = f"<evidence {' '.join(attributes)}>\n{passage}\n</evidence>"
        candidate = "\n\n".join((*blocks, block))
        if approx_tokens(candidate) <= max_tokens:
            blocks.append(block)
            included.append(ref.handle)
        else:
            budget_exhausted = True
            omitted.append(ref.handle)

    return PackedEvidence(
        text="\n\n".join(blocks),
        included=tuple(included),
        omitted=tuple(omitted),
    )


def neutralize(text: str) -> str:
    """Prevent retrieved content from opening or closing evidence delimiters."""
    return re.sub(
        r"</?evidence", lambda match: match.group(0).replace("<", "["), text, flags=re.I
    )
