"""Private, content-addressed storage for validated BM25S indexes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import bm25s  # type: ignore[import-untyped]

from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.lexical import (
    _HEX_SHA256,
    BM25_SCORING_SETTINGS,
    BM25S_VERSION,
    LEXICAL_INDEX_SCHEMA_VERSION,
    SCIENTIFIC_BM25_IDENTITY,
    BuiltLexicalIndex,
    IndexRole,
    LexicalIndexManifest,
    LexicalIndexRow,
    _canonical_sha256,
)
from research_platform.search.lexical_analyzer import (
    ANALYZER_ID,
    ANALYZER_REVISION,
    NORMALIZATION_REVISION,
)
from research_platform.search.profiles import RetrievalProfile

_STABLE_EVIDENCE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


def _validate_profile(profile: RetrievalProfile) -> None:
    if profile.lexical_index != SCIENTIFIC_BM25_IDENTITY:
        raise ValueError("profile does not select this BM25S analyzer and scoring")


@dataclass(frozen=True)
class SavedLexicalIndex:
    """Immutable content-addressed local artifact and storage accounting."""

    artifact_id: str
    path: Path
    storage_bytes: int
    file_count: int


_MANIFEST_FILE = "manifest.json"
_ROW_MAP_FILE = "rows.json"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_private(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def _private_size(path: Path) -> tuple[int, int]:
    files = [item for item in path.rglob("*") if item.is_file()]
    return sum(item.stat().st_size for item in files), len(files)


def save_lexical_index(
    index: BuiltLexicalIndex, artifact_root: Path
) -> SavedLexicalIndex:
    """Atomically publish an immutable content-addressed local BM25S artifact."""
    root = Path(artifact_root)
    if root.is_symlink():
        raise ValueError("lexical artifact root must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError("lexical artifact root must be a directory")
    root.chmod(0o700)
    stage = Path(tempfile.mkdtemp(prefix=".building-", dir=root))
    target: Path | None = None
    try:
        index_dir = stage / "bm25"
        index.engine.save(
            index_dir, corpus=None, show_progress=False, leave_progress=False
        )
        corpus_path = index_dir / "corpus.jsonl"
        if corpus_path.exists():
            raise RuntimeError("BM25S artifact unexpectedly contains a text corpus")
        row_bytes = json.dumps(
            index.to_row_map(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        _write_private(stage / _ROW_MAP_FILE, row_bytes)
        files: dict[str, str] = {}
        for file_path in sorted(index_dir.rglob("*")):
            if file_path.is_symlink():
                raise ValueError("BM25S artifact must not contain symlinks")
            if not file_path.is_file():
                continue
            relative_path = file_path.relative_to(stage).as_posix()
            file_path.chmod(0o600)
            files[relative_path] = _file_sha256(file_path)
        for directory in sorted(
            (item for item in stage.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            directory.chmod(0o700)
        payload: dict[str, object] = {
            **index.to_manifest_dict(),
            "row_map_file": _ROW_MAP_FILE,
            "files": files,
        }
        artifact_id = _canonical_sha256(payload)
        manifest_bytes = json.dumps(
            {**payload, "artifact_id": artifact_id},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        _write_private(stage / _MANIFEST_FILE, manifest_bytes)
        stage.chmod(0o700)
        target = root / artifact_id.removeprefix("sha256:")
        if target.exists():
            load_lexical_index(
                target,
                expected_profile=index.profile,
                expected_role=index.manifest.role,
                allow_draft=index.manifest.snapshot_status == "draft",
            )
            shutil.rmtree(stage)
            size_bytes, count = _private_size(target)
            return SavedLexicalIndex(artifact_id, target, size_bytes, count)
        try:
            os.rename(stage, target)
        except FileExistsError:
            if not target.exists():
                raise
            load_lexical_index(
                target,
                expected_profile=index.profile,
                expected_role=index.manifest.role,
                allow_draft=index.manifest.snapshot_status == "draft",
            )
            shutil.rmtree(stage)
        size_bytes, count = _private_size(target)
        return SavedLexicalIndex(artifact_id, target, size_bytes, count)
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid lexical artifact file: {path.name}") from exc


def load_lexical_index(
    artifact_path: Path,
    *,
    expected_profile: RetrievalProfile,
    expected_role: IndexRole,
    allow_draft: bool = False,
    mmap: bool = True,
) -> BuiltLexicalIndex:
    """Load an artifact only after profile, row-map and file hashes validate."""
    _validate_profile(expected_profile)
    if bm25s.__version__ != BM25S_VERSION:
        raise RuntimeError(
            f"BM25S {BM25S_VERSION} is required; found {bm25s.__version__}"
        )
    path = Path(artifact_path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("lexical artifact path must be a real directory")
    if path.stat().st_mode & 0o077:
        raise PermissionError("lexical artifact directory must be private (mode 700)")
    raw_manifest = _read_json(path / _MANIFEST_FILE)
    if not isinstance(raw_manifest, dict):
        raise ValueError("lexical manifest must be a JSON object")
    expected_fields = {
        "schema_version",
        "role",
        "snapshot_status",
        "snapshot",
        "profile_id",
        "lexical_index_id",
        "analyzer",
        "scoring",
        "row_count",
        "candidate_limit",
        "empty_token_row_count",
        "duplicate_content_row_count",
        "row_map_sha256",
        "row_map_file",
        "files",
        "artifact_id",
    }
    if set(raw_manifest) != expected_fields:
        raise ValueError("lexical manifest fields are incomplete or unknown")
    if raw_manifest["schema_version"] != LEXICAL_INDEX_SCHEMA_VERSION:
        raise ValueError("unsupported lexical artifact schema")
    if raw_manifest["role"] != expected_role:
        raise ValueError("lexical artifact role does not match the request")
    snapshot_status = raw_manifest["snapshot_status"]
    if snapshot_status not in {"draft", "finalized"}:
        raise ValueError("lexical artifact snapshot status is malformed")
    if snapshot_status == "draft" and not allow_draft:
        raise PermissionError("draft lexical index requires explicit evaluation access")
    if raw_manifest["profile_id"] != expected_profile.profile_id:
        raise ValueError("lexical artifact profile does not match the request")
    if raw_manifest["snapshot"] != expected_profile.snapshot.to_dict():
        raise ValueError("lexical artifact snapshot selection does not match")
    if raw_manifest["lexical_index_id"] != SCIENTIFIC_BM25_IDENTITY.configuration_id:
        raise ValueError("lexical artifact analyzer or implementation identity differs")
    expected_analyzer = {
        "id": ANALYZER_ID,
        "revision": ANALYZER_REVISION,
        "normalization_revision": NORMALIZATION_REVISION,
    }
    if raw_manifest["analyzer"] != expected_analyzer:
        raise ValueError("lexical artifact analyzer metadata differs")
    if raw_manifest["scoring"] != BM25_SCORING_SETTINGS.to_dict():
        raise ValueError("lexical artifact scoring configuration differs")
    candidate_limit = expected_profile.candidate_limits.lexical_top_k
    if raw_manifest["candidate_limit"] != candidate_limit:
        raise ValueError("lexical artifact candidate limit does not match the profile")
    if raw_manifest["row_map_file"] != _ROW_MAP_FILE:
        raise ValueError("unsupported lexical row-map filename")
    artifact_id = raw_manifest["artifact_id"]
    if not isinstance(artifact_id, str):
        raise ValueError("lexical artifact ID is malformed")
    payload = dict(raw_manifest)
    del payload["artifact_id"]
    if artifact_id != _canonical_sha256(payload):
        raise ValueError("lexical artifact manifest checksum does not match")
    expected_path_name = artifact_id.removeprefix("sha256:")
    if path.name != expected_path_name:
        raise ValueError("lexical artifact directory name does not match its identity")

    file_hashes = raw_manifest["files"]
    if not isinstance(file_hashes, dict) or not file_hashes:
        raise ValueError("lexical artifact file checksums are missing")
    actual_files: set[str] = set()
    for file_path in path.rglob("*"):
        if file_path.is_symlink():
            raise ValueError("lexical artifact must not contain symlinks")
        if file_path.is_file():
            relative_path = file_path.relative_to(path).as_posix()
            if relative_path in {_MANIFEST_FILE, _ROW_MAP_FILE}:
                continue
            if file_path.name == "corpus.jsonl":
                raise ValueError("lexical artifact must not contain a text corpus")
            actual_files.add(relative_path)
    if actual_files != set(file_hashes):
        raise ValueError("lexical artifact file set differs from its manifest")
    for name, digest in file_hashes.items():
        if (
            not isinstance(name, str)
            or name.startswith("/")
            or ".." in Path(name).parts
            or not isinstance(digest, str)
            or _HEX_SHA256.fullmatch(digest) is None
        ):
            raise ValueError("lexical artifact file checksum entry is malformed")
        candidate = path / name
        if not candidate.is_file() or _file_sha256(candidate) != digest:
            raise ValueError("lexical artifact file checksum does not match")
    row_map = _read_json(path / _ROW_MAP_FILE)
    if not isinstance(row_map, list) or any(
        not isinstance(row, dict) for row in row_map
    ):
        raise ValueError("lexical row map must be a list of JSON objects")
    rows = tuple(LexicalIndexRow.from_dict(row) for row in row_map)
    row_count = raw_manifest["row_count"]
    candidate_limit_value = raw_manifest["candidate_limit"]
    empty_count = raw_manifest["empty_token_row_count"]
    duplicate_count = raw_manifest["duplicate_content_row_count"]
    for name, value in (
        ("row_count", row_count),
        ("candidate_limit", candidate_limit_value),
        ("empty_token_row_count", empty_count),
        ("duplicate_content_row_count", duplicate_count),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"lexical manifest {name} is invalid")
    if row_count != len(rows) or row_count == 0:
        raise ValueError("lexical row count differs from its row map")
    if candidate_limit_value == 0:
        raise ValueError("lexical candidate limit must be positive")
    if empty_count > row_count or duplicate_count > row_count:
        raise ValueError("lexical manifest counts exceed its row count")
    if tuple(row.row for row in rows) != tuple(range(len(rows))):
        raise ValueError("lexical row positions are not contiguous")
    if len({row.stable_id for row in rows}) != len(rows):
        raise ValueError("lexical row map contains duplicate stable IDs")
    if expected_role == "evidence":
        if any(
            _STABLE_EVIDENCE_ID.fullmatch(row.stable_id) is None
            or row.source_artifact_sha256 is None
            or row.document_id is None
            or row.extraction_id is None
            or row.has_title is not None
            or row.has_abstract is not None
            for row in rows
        ):
            raise ValueError("evidence row map metadata is inconsistent")
    elif any(
        row.stable_id != row.paper_id
        or row.source_artifact_sha256 is not None
        or row.document_id is not None
        or row.extraction_id is not None
        or row.has_title is None
        or row.has_abstract is None
        or row.has_title != (row.title_sha256 is not None)
        or row.has_abstract != (row.abstract_sha256 is not None)
        for row in rows
    ):
        raise ValueError("paper row map metadata is inconsistent")
    row_payload = [row.to_dict() for row in rows]
    row_map_sha256 = _canonical_sha256(row_payload)
    if raw_manifest["row_map_sha256"] != row_map_sha256:
        raise ValueError("lexical row-map checksum does not match")
    content_counts: dict[str, int] = {}
    for row in rows:
        content_counts[row.content_sha256] = (
            content_counts.get(row.content_sha256, 0) + 1
        )
    duplicate_rows = sum(count - 1 for count in content_counts.values() if count > 1)
    if duplicate_rows != duplicate_count:
        raise ValueError("lexical duplicate-content count does not match")

    selection = SnapshotSelection.from_dict(
        cast(dict[str, object], raw_manifest["snapshot"])
    )
    manifest = LexicalIndexManifest(
        role=expected_role,
        snapshot_status=snapshot_status,
        snapshot=selection,
        profile_id=expected_profile.profile_id,
        lexical_index_id=SCIENTIFIC_BM25_IDENTITY.configuration_id,
        row_count=row_count,
        candidate_limit=candidate_limit_value,
        empty_token_row_count=empty_count,
        duplicate_content_row_count=duplicate_count,
        row_map_sha256=row_map_sha256,
        scoring=BM25_SCORING_SETTINGS,
    )
    engine = bm25s.BM25.load(
        path / "bm25",
        load_corpus=False,
        mmap=mmap,
        show_progress=False,
    )
    if engine.scores["num_docs"] != row_count:
        raise ValueError("BM25S document count differs from its row map")
    actual_scoring = {
        "method": engine.method,
        "idf_method": engine.idf_method,
        "k1": engine.k1,
        "b": engine.b,
        "delta": engine.delta,
        "dtype": engine.dtype,
        "int_dtype": engine.int_dtype,
        "backend": engine.backend,
        "csc_backend": engine.csc_backend,
    }
    expected_scoring = BM25_SCORING_SETTINGS.to_dict()
    expected_scoring.pop("auto_compile")
    if actual_scoring != expected_scoring:
        raise ValueError("loaded BM25S scoring settings differ from the profile")
    if engine._original_version != BM25S_VERSION:
        raise ValueError("saved BM25S index version differs from the runtime")
    engine.corpus = None
    return BuiltLexicalIndex(
        profile=expected_profile, manifest=manifest, rows=rows, engine=engine
    )
