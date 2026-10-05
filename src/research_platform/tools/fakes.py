"""Deterministic in-memory application services for agent workflow tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

from research_platform.discovery.online import (
    DiscoveredPaper,
    DiscoveryBudgetExceeded,
)
from research_platform.ingestion.evidence import EvidenceKind, SourceLocation
from research_platform.ingestion.identity import is_valid_paper_id
from research_platform.search.application_errors import SearchDependencyUnavailable
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    PaperHit,
    RankedComponent,
    RetrievalMode,
    SearchOperation,
    SearchRequest,
    SearchResponse,
)
from research_platform.search.paper_graph import (
    CitationDirection,
    CitationEndpointStatus,
    CitationGraphCursor,
    CitationGraphEdge,
    CitationGraphEndpoint,
    CitationGraphPage,
)
from research_platform.search.paper_reads import (
    MetadataAvailability,
    PaperReadStatus,
    SnapshotPaperRead,
)
from research_platform.search.paper_related import (
    RelatedPaper,
    RelatedPapersPage,
    RelationKind,
    rank_related,
)
from research_platform.search.paper_similarity import SimilarPaper
from research_platform.tools.research_tools import (
    CitationService,
    PaperService,
    RelatedService,
    SearchService,
)

_FAKE_NAMESPACE = UUID("12345678-1234-5678-1234-567812345678")
_FAKE_PROFILE_ID = "sha256:" + "1" * 64


@dataclass(frozen=True)
class FakePaper:
    """Small paper record used by the fake service bundle."""

    paper_id: str
    title: str
    publication_year: int


@dataclass(frozen=True)
class FakePassage:
    """One searchable passage attached to a fake paper."""

    chunk_id: str
    paper_id: str
    text: str
    kind: str = "text"


@dataclass(frozen=True)
class FakeCorpus:
    """In-memory papers, passages and stored citation edges."""

    snapshot_id: UUID
    papers: tuple[FakePaper, ...]
    passages: tuple[FakePassage, ...]
    citations: tuple[tuple[str, str], ...] = ()
    failing_queries: frozenset[str] = frozenset()


class FakeDiscoveryService:
    """Deterministic offline discovery results with recorded input arguments."""

    def __init__(
        self,
        papers: tuple[DiscoveredPaper, ...] = (),
        *,
        budget_error: DiscoveryBudgetExceeded | None = None,
    ) -> None:
        self.papers = papers
        self.budget_error = budget_error
        self.calls: list[dict[str, object]] = []

    async def discover(
        self,
        *,
        run_id: UUID | None,
        question: str,
        query: str,
        year_from: int | None,
        year_to: int | None,
        limit: int,
    ) -> tuple[DiscoveredPaper, ...]:
        self.calls.append(
            {
                "run_id": run_id,
                "question": question,
                "query": query,
                "year_from": year_from,
                "year_to": year_to,
                "limit": limit,
            }
        )
        if self.budget_error is not None:
            raise self.budget_error
        return tuple(
            paper
            for paper in self.papers
            if (
                year_from is None
                or (
                    paper.publication_year is not None
                    and paper.publication_year >= year_from
                )
            )
            and (
                year_to is None
                or (
                    paper.publication_year is not None
                    and paper.publication_year <= year_to
                )
            )
        )[:limit]


class FakeSimilarityReader:
    """Deterministic semantic paper results with recorded call arguments."""

    def __init__(
        self,
        similar_papers: tuple[SimilarPaper, ...] = (),
        uningested_papers: tuple[SimilarPaper, ...] = (),
    ) -> None:
        self.similar_papers = similar_papers
        self.uningested_papers = uningested_papers
        self.similar_calls: list[dict[str, object]] = []
        self.uningested_calls: list[dict[str, object]] = []

    async def similar_to_paper(
        self, paper_id: str, *, generation: int, limit: int
    ) -> tuple[SimilarPaper, ...]:
        self.similar_calls.append(
            {"paper_id": paper_id, "generation": generation, "limit": limit}
        )
        return self.similar_papers[:limit]

    async def uningested_for_question(
        self,
        question: str,
        *,
        limit: int = 5,
        minimum_similarity: float = 0.5,
    ) -> tuple[SimilarPaper, ...]:
        self.uningested_calls.append(
            {
                "question": question,
                "limit": limit,
                "minimum_similarity": minimum_similarity,
            }
        )
        return tuple(
            paper
            for paper in self.uningested_papers
            if paper.similarity >= minimum_similarity
        )[:limit]


class FakeServices:
    """Four deterministic services backed by one immutable fake corpus."""

    def __init__(self, corpus: FakeCorpus) -> None:
        self.corpus = corpus
        self._papers = {paper.paper_id: paper for paper in corpus.papers}

    async def execute(
        self, request: SearchRequest, *, request_id: str
    ) -> SearchResponse[PaperHit] | SearchResponse[EvidenceHit]:
        query = request.query.lower()
        if query in self.corpus.failing_queries:
            raise SearchDependencyUnavailable("configured fake search failure")
        allowed_ids = set(request.filters.paper_ids or ())
        eligible_papers = tuple(
            paper
            for paper in self.corpus.papers
            if (
                request.filters.year_from is None
                or paper.publication_year >= request.filters.year_from
            )
            and (
                request.filters.year_to is None
                or paper.publication_year <= request.filters.year_to
            )
            and (not allowed_ids or paper.paper_id in allowed_ids)
        )
        eligible_passage_count = 0
        matching: list[tuple[int, FakePassage]] = []
        for passage in self.corpus.passages:
            paper = self._papers.get(passage.paper_id)
            if paper is None:
                continue
            if request.filters.year_from is not None and (
                paper.publication_year < request.filters.year_from
            ):
                continue
            if request.filters.year_to is not None and (
                paper.publication_year > request.filters.year_to
            ):
                continue
            if allowed_ids and passage.paper_id not in allowed_ids:
                continue
            if request.filters.evidence_kinds is not None and (
                passage.kind not in request.filters.evidence_kinds
            ):
                continue
            eligible_passage_count += 1
            score = sum(word in passage.text.lower() for word in query.split())
            if score:
                matching.append((score, passage))
        matching.sort(key=lambda item: (-item[0], item[1].chunk_id))

        if request.operation is SearchOperation.EVIDENCE_SEARCH:
            selected = matching[: request.limit]
            hits = tuple(
                _evidence_hit(passage, index, score)
                for index, (score, passage) in enumerate(selected, start=1)
            )
            return SearchResponse(
                request_id=request_id,
                snapshot_id=request.snapshot_id,
                retrieval_profile_id=request.retrieval_profile_id,
                effective_configuration_id=_FAKE_PROFILE_ID,
                requested_mode=RetrievalMode.RERANKED,
                effective_mode=RetrievalMode.RERANKED,
                hits=hits,
                eligible_count=eligible_passage_count,
            )

        grouped: dict[str, list[tuple[int, FakePassage]]] = {}
        for item in matching:
            grouped.setdefault(item[1].paper_id, []).append(item)
        ranked_papers = sorted(
            grouped,
            key=lambda paper_id: (
                -grouped[paper_id][0][0],
                grouped[paper_id][0][1].chunk_id,
            ),
        )
        selected_papers = ranked_papers[: request.limit]
        paper_hits: list[PaperHit] = []
        for rank, paper_id in enumerate(selected_papers, start=1):
            paper = self._papers[paper_id]
            supporting = tuple(
                _evidence_hit(passage, passage_rank, score)
                for passage_rank, (score, passage) in enumerate(
                    grouped[paper_id][:3], start=1
                )
            )
            score = grouped[paper_id][0][0]
            paper_hits.append(
                PaperHit(
                    paper_id=paper_id,
                    title=paper.title,
                    publication_year=paper.publication_year,
                    rank=rank,
                    component_scores=ComponentScores(
                        reranker=RankedComponent(rank=rank, score=float(score))
                    ),
                    supporting_evidence=supporting,
                )
            )
        return SearchResponse(
            request_id=request_id,
            snapshot_id=request.snapshot_id,
            retrieval_profile_id=request.retrieval_profile_id,
            effective_configuration_id=_FAKE_PROFILE_ID,
            requested_mode=RetrievalMode.RERANKED,
            effective_mode=RetrievalMode.RERANKED,
            hits=tuple(paper_hits),
            eligible_count=len(eligible_papers),
        )

    async def read_paper(self, snapshot_id: UUID, paper_id: str) -> SnapshotPaperRead:
        if not is_valid_paper_id(paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        paper = self._papers.get(paper_id)
        if paper is None:
            return SnapshotPaperRead(
                paper_id=paper_id,
                snapshot_id=snapshot_id,
                status=PaperReadStatus.UNKNOWN,
                title=None,
                publication_year=None,
                metadata_availability=MetadataAvailability(
                    title=False, abstract=False, publication_year=False
                ),
            )
        return SnapshotPaperRead(
            paper_id=paper_id,
            snapshot_id=snapshot_id,
            status=PaperReadStatus.IN_SNAPSHOT,
            title=paper.title,
            publication_year=paper.publication_year,
            metadata_availability=MetadataAvailability(
                title=True, abstract=False, publication_year=True
            ),
            document_id=_stable_uuid(f"document:{paper_id}"),
            document_version="fake-v1",
            document_version_kind="published",
        )

    async def read_one_hop(
        self,
        snapshot_id: UUID,
        paper_id: str,
        direction: CitationDirection,
        *,
        limit: int = 20,
        cursor: CitationGraphCursor | None = None,
    ) -> CitationGraphPage:
        if cursor is not None:
            raise ValueError("fake citation service does not paginate")
        if not is_valid_paper_id(paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if direction is CitationDirection.REFERENCES:
            connected = [
                cited for citing, cited in self.corpus.citations if citing == paper_id
            ]
        else:
            connected = [
                citing for citing, cited in self.corpus.citations if cited == paper_id
            ]
        endpoints = sorted(set(connected))[:limit]
        edges = tuple(
            CitationGraphEdge(
                endpoint=_citation_endpoint(self._papers.get(endpoint), endpoint),
                source="fake",
            )
            for endpoint in endpoints
        )
        return CitationGraphPage(
            snapshot_id=snapshot_id,
            paper_id=paper_id,
            direction=direction,
            source_status=(
                PaperReadStatus.IN_SNAPSHOT
                if paper_id in self._papers
                else PaperReadStatus.UNKNOWN
            ),
            limit=limit,
            edges=edges,
            next_cursor=None,
            coverage_note="Fake citations include only configured edges.",
        )

    async def find_related(
        self, snapshot_id: UUID, paper_id: str, *, limit: int = 10
    ) -> RelatedPapersPage:
        if not is_valid_paper_id(paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        rows: list[RelatedPaper] = []
        source_refs = {
            cited for citing, cited in self.corpus.citations if citing == paper_id
        }
        source_citers = {
            citing for citing, cited in self.corpus.citations if cited == paper_id
        }
        for candidate in self.corpus.papers:
            if candidate.paper_id == paper_id:
                continue
            candidate_refs = {
                cited
                for citing, cited in self.corpus.citations
                if citing == candidate.paper_id
            }
            candidate_citers = {
                citing
                for citing, cited in self.corpus.citations
                if cited == candidate.paper_id
            }
            shared = len(source_refs & candidate_refs)
            co_cited = len(source_citers & candidate_citers)
            if shared or co_cited:
                relations = tuple(
                    relation
                    for relation, count in (
                        (RelationKind.SHARED_REFERENCES, shared),
                        (RelationKind.CO_CITED, co_cited),
                    )
                    if count
                )
                rows.append(
                    RelatedPaper(
                        paper_id=candidate.paper_id,
                        title=candidate.title,
                        publication_year=candidate.publication_year,
                        shared_reference_count=shared,
                        co_citation_count=co_cited,
                        score=shared + co_cited,
                        relations=relations,
                    )
                )
        source_status = (
            PaperReadStatus.IN_SNAPSHOT
            if paper_id in self._papers
            else PaperReadStatus.UNKNOWN
        )
        ranked = (
            rank_related(rows, limit)
            if source_status is PaperReadStatus.IN_SNAPSHOT
            else ()
        )
        return RelatedPapersPage(
            snapshot_id=snapshot_id,
            paper_id=paper_id,
            source_status=source_status,
            papers=ranked,
            coverage_note="Fake related papers use configured citation edges.",
        )


def fake_services(
    corpus: FakeCorpus,
) -> tuple[SearchService, PaperService, CitationService, RelatedService]:
    """Build the search, paper, citation and related services for one corpus."""
    services = FakeServices(corpus)
    return services, services, services, services


def _evidence_hit(passage: FakePassage, rank: int, score: int) -> EvidenceHit:
    try:
        kind: EvidenceKind = passage.kind  # type: ignore[assignment]
        if kind not in (
            "text",
            "table",
            "table_row_group",
            "caption",
            "figure",
            "equation",
        ):
            raise ValueError
    except ValueError:
        kind = "text"
    return EvidenceHit(
        chunk_id=passage.chunk_id,
        source_evidence_ids=(f"source:{passage.chunk_id}",),
        paper_id=passage.paper_id,
        document_id=_stable_uuid(f"document:{passage.paper_id}"),
        document_version="fake-v1",
        document_version_kind="published",
        extraction_id=_stable_uuid(f"extraction:{passage.paper_id}"),
        chunking_configuration_id=None,
        kind=kind,
        source_location=SourceLocation(page_index_zero_based=0),
        rank=rank,
        component_scores=ComponentScores(
            reranker=RankedComponent(rank=rank, score=float(score))
        ),
        text=passage.text,
    )


def _citation_endpoint(paper: FakePaper | None, paper_id: str) -> CitationGraphEndpoint:
    if paper is None:
        return CitationGraphEndpoint(
            status=CitationEndpointStatus.OUTSIDE_SNAPSHOT,
            paper_id=paper_id,
            title=None,
            publication_year=None,
        )
    return CitationGraphEndpoint(
        status=CitationEndpointStatus.IN_SNAPSHOT,
        paper_id=paper.paper_id,
        title=paper.title,
        publication_year=paper.publication_year,
    )


def _stable_uuid(value: str) -> UUID:
    return uuid5(_FAKE_NAMESPACE, value)
