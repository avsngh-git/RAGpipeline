"""Paper identity, manifest import and real citation-edge persistence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.identity import ExternalIdentifier


class IdentityConflict(ValueError):
    """Reliable external identifiers point to different local paper records."""


@dataclass(frozen=True)
class ManifestPaperImport:
    manifest_id: UUID
    collection_id: UUID
    new_papers: int
    imported_candidates: int
    resolved_citations_added: int
    unresolved_citations_added: int


class PaperRepository:
    """Persist verified paper identity and citation endpoints."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def import_approved_manifest(self, manifest_id: UUID) -> ManifestPaperImport:
        """Import only included candidates from an immutable approved manifest."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                manifest = await connection.fetchrow(
                    """
                    SELECT id, version, status
                    FROM discovery_manifests
                    WHERE id = $1
                    FOR SHARE
                    """,
                    manifest_id,
                )
                if manifest is None or manifest["status"] != "approved":
                    raise ValueError("only an approved manifest can be imported")

                candidates = await connection.fetch(
                    """
                    SELECT i.candidate_id, i.reason, c.openalex_id, c.title,
                           c.publication_year, c.doi, c.metadata
                    FROM discovery_manifest_items AS i
                    JOIN discovery_candidates AS c ON c.id = i.candidate_id
                    WHERE i.manifest_id = $1 AND i.decision = 'include'
                    ORDER BY c.openalex_id
                    """,
                    manifest_id,
                )
                if not candidates:
                    raise ValueError("approved manifest has no included candidates")

                collection_id = await connection.fetchval(
                    """
                    INSERT INTO collections
                        (name, description, discovery_manifest_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (discovery_manifest_id)
                    DO UPDATE SET discovery_manifest_id = EXCLUDED.discovery_manifest_id
                    RETURNING id
                    """,
                    f"phase1-manifest-v{manifest['version']}-{manifest_id.hex[:8]}",
                    f"Imported from approved discovery manifest {manifest_id}",
                    manifest_id,
                )
                if not isinstance(collection_id, UUID):
                    raise RuntimeError("database did not return a collection ID")

                new_papers = 0
                imported_candidates = 0
                citation_references: list[tuple[str, str]] = []
                for candidate in candidates:
                    paper_id, created = await self._resolve_paper_identity(
                        connection,
                        candidate["openalex_id"],
                        candidate["doi"],
                        candidate["title"],
                        candidate["publication_year"],
                        _as_json_object(candidate["metadata"]),
                    )
                    new_papers += int(created)
                    await self._persist_authors(
                        connection, paper_id, _as_json_object(candidate["metadata"])
                    )
                    await self._persist_document_versions(
                        connection, paper_id, _as_json_object(candidate["metadata"])
                    )
                    already_imported = await connection.fetchval(
                        """
                        SELECT 1 FROM manifest_paper_imports
                        WHERE manifest_id = $1 AND candidate_id = $2
                        """,
                        manifest_id,
                        candidate["candidate_id"],
                    )
                    await connection.execute(
                        """
                        INSERT INTO collection_papers
                            (collection_id, paper_id, inclusion_reason)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (collection_id, paper_id)
                        DO UPDATE SET inclusion_reason = EXCLUDED.inclusion_reason
                        """,
                        collection_id,
                        paper_id,
                        candidate["reason"],
                    )
                    await connection.execute(
                        """
                        INSERT INTO manifest_paper_imports
                            (manifest_id, candidate_id, paper_id, collection_id)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (manifest_id, candidate_id)
                        DO UPDATE SET paper_id = EXCLUDED.paper_id,
                                      collection_id = EXCLUDED.collection_id
                        """,
                        manifest_id,
                        candidate["candidate_id"],
                        paper_id,
                        collection_id,
                    )
                    imported_candidates += int(already_imported is None)
                    for target_id in _referenced_openalex_ids(
                        _as_json_object(candidate["metadata"])
                    ):
                        citation_references.append((paper_id, target_id))

                resolved_added = 0
                unresolved_added = 0
                for citing_paper_id, target_openalex_id in citation_references:
                    target_paper_id = await connection.fetchval(
                        """
                        SELECT id FROM papers WHERE openalex_id = $1
                        UNION
                        SELECT paper_id FROM paper_identifiers
                        WHERE namespace = 'openalex' AND normalized_identifier = $1
                        LIMIT 1
                        """,
                        target_openalex_id,
                    )
                    if target_paper_id is not None:
                        inserted = await connection.fetchval(
                            """
                            INSERT INTO citations (citing_paper_id, cited_paper_id, source)
                            VALUES ($1, $2, 'openalex')
                            ON CONFLICT (citing_paper_id, cited_paper_id) DO NOTHING
                            RETURNING citing_paper_id
                            """,
                            citing_paper_id,
                            target_paper_id,
                        )
                        resolved_added += int(inserted is not None)
                    else:
                        inserted = await connection.fetchval(
                            """
                            INSERT INTO unresolved_citations
                                (citing_paper_id, target_namespace, target_identifier,
                                 source, metadata)
                            VALUES ($1, 'openalex', $2, 'openalex', $3::jsonb)
                            ON CONFLICT
                                (citing_paper_id, target_namespace, target_identifier, source)
                            DO NOTHING
                            RETURNING id
                            """,
                            citing_paper_id,
                            target_openalex_id,
                            json.dumps({"discovery_manifest_id": str(manifest_id)}),
                        )
                        unresolved_added += int(inserted is not None)

                await connection.execute(
                    """
                    UPDATE unresolved_citations AS unresolved
                    SET resolved_paper_id = target.id,
                        resolved_at = COALESCE(unresolved.resolved_at, now())
                    FROM paper_identifiers AS identifier
                    JOIN papers AS target ON target.id = identifier.paper_id
                    WHERE unresolved.target_namespace = 'openalex'
                      AND unresolved.target_identifier = identifier.normalized_identifier
                      AND identifier.namespace = 'openalex'
                      AND unresolved.resolved_paper_id IS NULL
                    """
                )
                newly_resolved = await connection.fetch(
                    """
                    INSERT INTO citations (citing_paper_id, cited_paper_id, source)
                    SELECT citing_paper_id, resolved_paper_id, source
                    FROM unresolved_citations
                    WHERE resolved_paper_id IS NOT NULL
                    ON CONFLICT (citing_paper_id, cited_paper_id) DO NOTHING
                    RETURNING citing_paper_id
                    """
                )
                resolved_added += len(newly_resolved)

        return ManifestPaperImport(
            manifest_id=manifest_id,
            collection_id=collection_id,
            new_papers=new_papers,
            imported_candidates=imported_candidates,
            resolved_citations_added=resolved_added,
            unresolved_citations_added=unresolved_added,
        )

    async def _persist_authors(
        self,
        connection: asyncpg.Connection,
        paper_id: str,
        metadata: Mapping[str, object],
    ) -> None:
        raw_authorships = metadata.get("authorships", [])
        if not isinstance(raw_authorships, list):
            raise ValueError("OpenAlex authorships must be a list")
        await connection.execute(
            "DELETE FROM paper_authors WHERE paper_id = $1", paper_id
        )
        for position, raw_authorship in enumerate(raw_authorships):
            if not isinstance(raw_authorship, Mapping):
                continue
            raw_author = raw_authorship.get("author")
            if not isinstance(raw_author, Mapping):
                continue
            raw_id = raw_author.get("id")
            display_name = raw_author.get("display_name")
            if not isinstance(raw_id, str) or not isinstance(display_name, str):
                continue
            display_name = display_name.strip()
            if not display_name:
                continue
            normalized_author_id = raw_id.removeprefix("https://openalex.org/")
            if not re.fullmatch(r"A[0-9]+", normalized_author_id):
                continue
            author_id = await connection.fetchval(
                """
                INSERT INTO authors (openalex_id, display_name)
                VALUES ($1, $2)
                ON CONFLICT (openalex_id) DO UPDATE
                    SET display_name = EXCLUDED.display_name
                RETURNING id
                """,
                normalized_author_id,
                display_name,
            )
            if not isinstance(author_id, int):
                raise RuntimeError("database did not return an author ID")
            await connection.execute(
                """
                INSERT INTO paper_authors (paper_id, author_id, author_position)
                VALUES ($1, $2, $3)
                ON CONFLICT (paper_id, author_id) DO UPDATE
                    SET author_position = EXCLUDED.author_position
                """,
                paper_id,
                author_id,
                position,
            )

    async def _persist_document_versions(
        self,
        connection: asyncpg.Connection,
        paper_id: str,
        metadata: Mapping[str, object],
    ) -> None:
        raw_locations = metadata.get("locations", [])
        if not isinstance(raw_locations, list):
            raise ValueError("OpenAlex locations must be a list")
        primary_location = metadata.get("primary_location")
        locations = list(raw_locations)
        if isinstance(primary_location, Mapping) and primary_location not in locations:
            locations.insert(0, primary_location)
        seen: set[tuple[str, str]] = set()
        for position, raw_location in enumerate(locations):
            if not isinstance(raw_location, Mapping):
                continue
            source = raw_location.get("source")
            source_identifier = (
                source.get("id") if isinstance(source, Mapping) else None
            )
            source_name = (
                source.get("display_name") if isinstance(source, Mapping) else None
            )
            if isinstance(source_identifier, str):
                source_type = "openalex-location:" + source_identifier
            elif isinstance(source_name, str) and source_name.strip():
                source_type = "openalex-location-name:" + source_name.strip().lower()
            else:
                source_type = f"openalex-location-unknown:{position}"
            raw_version = raw_location.get("version")
            version = raw_version.strip() if isinstance(raw_version, str) else "unknown"
            if not version:
                version = "unknown"
            identity = (source_type, version)
            if identity in seen:
                continue
            seen.add(identity)

            is_published = raw_location.get("is_published") is True
            normalized_version = version.lower()
            if is_published or normalized_version == "publishedversion":
                version_kind = "published"
            elif normalized_version in {"submittedversion", "preprint"}:
                version_kind = "preprint"
            elif normalized_version == "acceptedversion":
                version_kind = "other"
            else:
                version_kind = "unknown"
            source_url = raw_location.get("landing_page_url")
            if source_url is not None and not isinstance(source_url, str):
                source_url = None
            location_json = json.dumps(dict(raw_location), sort_keys=True)
            await connection.execute(
                """
                INSERT INTO documents
                    (paper_id, source_type, source_url, version, status,
                     version_kind, metadata)
                VALUES ($1, $2, $3, $4, 'metadata_only', $5, $6::jsonb)
                ON CONFLICT (paper_id, source_type, version) DO UPDATE
                    SET source_url = COALESCE(documents.source_url, EXCLUDED.source_url),
                        metadata = documents.metadata || EXCLUDED.metadata
                """,
                paper_id,
                source_type,
                source_url,
                version,
                version_kind,
                location_json,
            )

    async def _resolve_paper_identity(
        self,
        connection: asyncpg.Connection,
        openalex_id: str,
        doi: str | None,
        title: str | None,
        publication_year: int | None,
        metadata: Mapping[str, object],
    ) -> tuple[str, bool]:
        openalex_identifier = ExternalIdentifier("openalex", openalex_id)
        doi_identifier = ExternalIdentifier("doi", doi) if doi else None
        rows = await connection.fetch(
            """
            SELECT paper_id
            FROM paper_identifiers
            WHERE (namespace = 'openalex' AND normalized_identifier = $1)
               OR ($2::text IS NOT NULL AND namespace = 'doi'
                   AND normalized_identifier = $2)
            UNION
            SELECT id AS paper_id FROM papers WHERE openalex_id = $1
            """,
            openalex_identifier.normalized_value,
            doi_identifier.normalized_value if doi_identifier is not None else None,
        )
        paper_ids = {row["paper_id"] for row in rows}
        if len(paper_ids) > 1:
            raise IdentityConflict(
                f"OpenAlex and DOI identifiers disagree for {openalex_id}"
            )

        created = not paper_ids
        paper_id = (
            next(iter(paper_ids)) if paper_ids else openalex_identifier.normalized_value
        )
        await connection.execute(
            """
            INSERT INTO papers (id, openalex_id, title, publication_year, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (id) DO UPDATE
                SET openalex_id = COALESCE(papers.openalex_id, EXCLUDED.openalex_id),
                    title = COALESCE(papers.title, EXCLUDED.title),
                    publication_year = COALESCE(
                        papers.publication_year, EXCLUDED.publication_year
                    ),
                    metadata = papers.metadata || EXCLUDED.metadata
            """,
            paper_id,
            openalex_identifier.normalized_value,
            title,
            publication_year,
            json.dumps(dict(metadata), sort_keys=True),
        )

        identifiers = [openalex_identifier]
        if doi_identifier is not None:
            identifiers.append(doi_identifier)
        for identifier in identifiers:
            existing_paper = await connection.fetchval(
                """
                SELECT paper_id FROM paper_identifiers
                WHERE namespace = $1 AND normalized_identifier = $2
                """,
                identifier.namespace,
                identifier.normalized_value,
            )
            if existing_paper is not None and existing_paper != paper_id:
                raise IdentityConflict(
                    f"{identifier.namespace} identifier maps to multiple papers"
                )
            await connection.execute(
                """
                INSERT INTO paper_identifiers
                    (paper_id, namespace, identifier, normalized_identifier,
                     verification_method)
                VALUES ($1, $2, $3, $3, 'openalex-work-record')
                ON CONFLICT (namespace, normalized_identifier) DO NOTHING
                """,
                paper_id,
                identifier.namespace,
                identifier.normalized_value,
            )
        return paper_id, created


def _as_json_object(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("database JSON object has an unexpected shape")
    return cast(Mapping[str, object], value)


def _referenced_openalex_ids(metadata: Mapping[str, object]) -> tuple[str, ...]:
    references = metadata.get("referenced_works", [])
    if not isinstance(references, list):
        raise ValueError("OpenAlex referenced_works must be a list")
    normalized: list[str] = []
    for reference in references:
        if not isinstance(reference, str):
            raise ValueError("OpenAlex referenced works must be string IDs")
        normalized.append(ExternalIdentifier("openalex", reference).normalized_value)
    return tuple(dict.fromkeys(normalized))
