from __future__ import annotations

import json
from dataclasses import replace
from uuid import UUID

import pytest

from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.lexical import (
    SCIENTIFIC_BM25_IDENTITY,
    EvidenceLexicalDocument,
    PaperLexicalDocument,
    build_evidence_index,
    build_paper_index,
)
from research_platform.search.lexical_artifacts import (
    load_lexical_index,
    save_lexical_index,
)
from research_platform.search.profiles import CandidateLimits, RetrievalProfile


def _profile() -> RetrievalProfile:
    selection = SnapshotSelection(
        snapshot_id=UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c"),
        snapshot_configuration_id="sha256:" + "1" * 64,
        chunk_selection_id="sha256:" + "2" * 64,
    )
    return RetrievalProfile(
        snapshot=selection,
        lexical_index=SCIENTIFIC_BM25_IDENTITY,
        dense_index=None,
        candidate_limits=CandidateLimits(
            lexical_top_k=50,
            dense_top_k=None,
            fused_top_k=None,
            rerank_top_k=None,
        ),
    )


def _evidence(stable_id: str, paper_id: str, text: str) -> EvidenceLexicalDocument:
    return EvidenceLexicalDocument(
        evidence_id=stable_id,
        paper_id=paper_id,
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        extraction_id=UUID("00000000-0000-0000-0000-000000000002"),
        source_artifact_sha256="a" * 64,
        text=text,
    )


def test_evidence_index_has_deterministic_rows_and_preserves_duplicate_text() -> None:
    repeated = "sha256:" + "1" * 64
    empty = "sha256:" + "2" * 64
    third = "sha256:" + "3" * 64
    index = build_evidence_index(
        (
            _evidence(third, "W3", "same source text"),
            _evidence(empty, "W1", ""),
            _evidence(repeated, "W2", "same source text"),
        ),
        _profile(),
    )

    assert index.manifest.role == "evidence"
    assert index.manifest.snapshot == _profile().snapshot
    assert index.manifest.profile_id == _profile().profile_id
    assert [row.stable_id for row in index.rows] == sorted((empty, repeated, third))
    assert [row.row for row in index.rows] == [0, 1, 2]
    assert index.manifest.row_count == 3
    assert index.manifest.empty_token_row_count == 1
    assert index.manifest.duplicate_content_row_count == 1
    assert index.rows[0].content_sha256 == index.rows[2].content_sha256
    assert index.rows[0].source_artifact_sha256 == "a" * 64
    assert index.engine.scores["num_docs"] == 3
    assert index.engine.corpus is None
    serialized = json.dumps(
        {"manifest": index.to_manifest_dict(), "rows": index.to_row_map()}
    )
    assert "same source text" not in serialized


def test_paper_index_keeps_missing_fields_and_empty_paper_rows() -> None:
    index = build_paper_index(
        (
            PaperLexicalDocument("W2", None, None),
            PaperLexicalDocument("W1", "Paper title", "Abstract content"),
        ),
        _profile(),
    )

    assert index.manifest.role == "paper"
    assert [row.paper_id for row in index.rows] == ["W1", "W2"]
    assert index.manifest.row_count == 2
    assert index.manifest.empty_token_row_count == 1
    assert index.rows[0].has_title is True
    assert index.rows[0].has_abstract is True
    assert index.rows[1].has_title is False
    assert index.rows[1].has_abstract is False
    assert index.rows[1].title_sha256 is None
    assert index.rows[1].abstract_sha256 is None
    assert index.engine.scores["num_docs"] == 2


def test_duplicate_authoritative_ids_are_rejected_but_duplicate_text_is_not() -> None:
    evidence = _evidence("sha256:" + "1" * 64, "W1", "text")
    with pytest.raises(ValueError, match="duplicate evidence IDs"):
        build_evidence_index((evidence, evidence), _profile())

    duplicate_paper = PaperLexicalDocument("W1", "Title", None)
    with pytest.raises(ValueError, match="duplicate paper IDs"):
        build_paper_index((duplicate_paper, duplicate_paper), _profile())


def test_index_builder_rejects_a_profile_with_another_lexical_identity() -> None:
    profile = _profile()
    incompatible = RetrievalProfile(
        snapshot=profile.snapshot,
        lexical_index=replace(
            SCIENTIFIC_BM25_IDENTITY, implementation_revision="other-revision"
        ),
        dense_index=None,
        candidate_limits=profile.candidate_limits,
    )
    with pytest.raises(ValueError, match="does not select this BM25S"):
        build_paper_index((PaperLexicalDocument("W1", "Title", None),), incompatible)


def test_invalid_source_artifact_checksum_is_rejected() -> None:
    with pytest.raises(ValueError, match="source_artifact_sha256"):
        EvidenceLexicalDocument(
            evidence_id="sha256:" + "1" * 64,
            paper_id="W1",
            document_id=UUID("00000000-0000-0000-0000-000000000001"),
            extraction_id=UUID("00000000-0000-0000-0000-000000000002"),
            source_artifact_sha256="invalid",
            text="evidence",
        )


def test_retriever_matches_independent_bm25_scores_and_order() -> None:
    import math

    from research_platform.search.lexical import LexicalRetriever

    ids = tuple("sha256:" + digit * 64 for digit in "123")
    profile = _profile()
    index = build_evidence_index(
        (
            _evidence(ids[0], "W1", "alpha beta"),
            _evidence(ids[1], "W2", "alpha alpha gamma"),
            _evidence(ids[2], "W3", "beta gamma"),
        ),
        profile,
    )
    hits = LexicalRetriever(index).search("alpha", limit=3)

    n_documents = 3
    document_frequency = 2
    average_length = 7.0 / 3.0
    inverse_document_frequency = math.log(
        1.0 + (n_documents - document_frequency + 0.5) / (document_frequency + 0.5)
    )
    expected = []
    for term_frequency, document_length in ((1, 2), (2, 3), (0, 2)):
        length_norm = 1.5 * (1.0 - 0.75 + 0.75 * document_length / average_length)
        expected.append(
            inverse_document_frequency * term_frequency / (term_frequency + length_norm)
            if term_frequency
            else 0.0
        )

    assert [hit.stable_id for hit in hits] == [ids[1], ids[0]]
    assert math.isclose(hits[0].score, expected[1], rel_tol=1e-5)
    assert math.isclose(hits[1].score, expected[0], rel_tol=1e-5)


def test_retriever_applies_eligibility_before_top_k_and_handles_empty_results() -> None:
    from research_platform.search.lexical import LexicalRetriever

    ids = tuple("sha256:" + digit * 64 for digit in "123")
    index = build_evidence_index(
        (
            _evidence(ids[0], "W1", "alpha beta"),
            _evidence(ids[1], "W2", "alpha alpha gamma"),
            _evidence(ids[2], "W3", "beta gamma"),
        ),
        _profile(),
    )
    search = LexicalRetriever(index)

    restricted = search.search("alpha", eligible_ids={ids[0]}, limit=1)
    assert [hit.stable_id for hit in restricted] == [ids[0]]
    assert search.search("alpha", eligible_ids=set()) == ()
    assert search.search("missing-token") == ()
    assert search.search("???") == ()
    with pytest.raises(ValueError, match="outside this lexical index"):
        search.search("alpha", eligible_ids={"sha256:" + "9" * 64})


def test_saved_index_is_content_addressed_private_and_reloads(tmp_path) -> None:
    from research_platform.search.lexical import LexicalRetriever

    profile = _profile()
    index = build_evidence_index(
        (
            _evidence("sha256:" + "1" * 64, "W1", "alpha beta"),
            _evidence("sha256:" + "2" * 64, "W2", "alpha gamma"),
        ),
        profile,
    )
    first = save_lexical_index(index, tmp_path / "lexical")

    assert first.path.is_dir()
    assert first.path.stat().st_mode & 0o777 == 0o700
    assert first.storage_bytes > 0
    assert first.file_count >= 7
    assert not (first.path / "bm25" / "corpus.jsonl").exists()
    assert not list((tmp_path / "lexical").glob(".building-*"))

    loaded = load_lexical_index(
        first.path,
        expected_profile=profile,
        expected_role="evidence",
        allow_draft=True,
    )
    assert loaded.manifest == index.manifest
    assert loaded.rows == index.rows
    before = LexicalRetriever(index).search("alpha", limit=2)
    after = LexicalRetriever(loaded).search("alpha", limit=2)
    assert [(hit.stable_id, hit.score) for hit in after] == [
        (hit.stable_id, hit.score) for hit in before
    ]

    second = save_lexical_index(index, tmp_path / "lexical")
    assert (second.artifact_id, second.path, second.storage_bytes) == (
        first.artifact_id,
        first.path,
        first.storage_bytes,
    )


def test_saved_index_rejects_profile_mismatch_and_tampered_files(tmp_path) -> None:
    from dataclasses import replace

    profile = _profile()
    index = build_paper_index((PaperLexicalDocument("W1", "title", None),), profile)
    saved = save_lexical_index(index, tmp_path / "lexical")
    other_snapshot = replace(
        profile.snapshot, snapshot_id=UUID("00000000-0000-0000-0000-000000000010")
    )
    other_profile = replace(profile, snapshot=other_snapshot)
    with pytest.raises(ValueError, match="profile does not match"):
        load_lexical_index(
            saved.path,
            expected_profile=other_profile,
            expected_role="paper",
            allow_draft=True,
        )

    with pytest.raises(PermissionError, match="explicit evaluation access"):
        load_lexical_index(saved.path, expected_profile=profile, expected_role="paper")

    index_file = saved.path / "bm25" / "data.csc.index.npy"
    index_file.chmod(0o600)
    with index_file.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="file checksum"):
        load_lexical_index(
            saved.path,
            expected_profile=profile,
            expected_role="paper",
            allow_draft=True,
        )


def test_cli_lexical_query_uses_saved_service_without_database(
    capsys, tmp_path
) -> None:
    import asyncio

    from research_platform.ingestion.cli import _execute, build_parser
    from research_platform.search.lexical_artifacts import save_lexical_index

    profile = _profile()
    index = build_evidence_index(
        (_evidence("sha256:" + "1" * 64, "W1", "rare scientific term"),),
        profile,
    )
    saved = save_lexical_index(index, tmp_path / "artifacts")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()), encoding="utf-8")
    args = build_parser().parse_args(
        [
            "index",
            "lexical-query",
            "--artifact-dir",
            str(saved.path),
            "--profile",
            str(profile_path),
            "--role",
            "evidence",
            "--evaluation",
            "--query",
            "scientific",
        ]
    )

    asyncio.run(_execute(args))
    output = json.loads(capsys.readouterr().out)
    assert output["profile_id"] == profile.profile_id
    assert output["role"] == "evidence"
    assert output["snapshot_status"] == "draft"
    assert [match["stable_id"] for match in output["matches"]] == ["sha256:" + "1" * 64]


def test_finalized_lexical_artifact_loads_without_evaluation_access(tmp_path) -> None:
    profile = _profile()
    index = build_paper_index(
        (PaperLexicalDocument("W1", "finalized title", None),),
        profile,
        snapshot_status="finalized",
    )
    saved = save_lexical_index(index, tmp_path / "lexical")

    loaded = load_lexical_index(
        saved.path, expected_profile=profile, expected_role="paper"
    )
    assert loaded.manifest.snapshot_status == "finalized"
