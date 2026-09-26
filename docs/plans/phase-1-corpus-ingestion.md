# Phase 1 — Corpus and ingestion

Status: detailed plan approved 2026-09-23; Phase 1 implementation is in
progress under the user’s explicit delegation on 2026-09-23. Original scope
approved 2026-09-22. The Phase 0 hosted CI entry gate passed on the fixed
revision; the P1-01 baseline and profiles are recorded below.

## Authority and working agreement

Read the [source of truth](../agents/scientific-research-platform-source-of-truth.md)
in full as required by AGENTS.md. Section 8.6 owns the corpus constraints.
[ADR-0001](../adr/0001-versioned-corpus-evidence.md) explains versioned evidence;
[ADR-0002](../adr/0002-finalize-validated-snapshots.md) explains snapshot acceptance.
[CONTEXT.md](../../CONTEXT.md) defines terms.

The user normally implements this project to learn Python. On 2026-09-23, the
user explicitly delegated the remaining Phase 1 implementation, tests and
documentation to the assistant. Preserve that delegation and the human review
gates recorded in the [Phase 1 handoff](phase-1-learning-handoff.md).

## Outcome and boundaries

Deliver a finalized snapshot containing 100 successfully ingested papers with
usable text and structured table evidence, verified provenance, safe recovery,
a rebuildable Qdrant index and a measured corpus quality report. First compare
extraction approaches on 10 papers. These counts are engineering milestones,
not proof of research coverage or retrieval quality.

The initial scope is English-language RAG, retrieval and reranking papers from
2020 through the recorded snapshot date, with explicit older foundational
exceptions. Include substantive contributions/evaluations and negative or mixed
findings. Broader ML research is the later expansion path.

Coverage questions:

1. When does hybrid retrieval outperform dense-only retrieval?
2. How much does cross-encoder reranking improve retrieval quality, and at what latency cost?
3. How do chunking choices affect evidence retrieval and citation support?

Use OpenAlex for discovery, metadata and real citation relationships. Acquire
full text through supported sources under documented permissions. Prefer the
published version, falling back to an eligible preprint, and identify the version
actually indexed. Preserve metadata-only and unresolved-reference records.

Phase 1 includes an explainable discovery shortlist and human-approved manifests.
It does not require a learned selection classifier, automated refresh, recursive
full-text citation expansion, background job queue, ingestion UI, full search API,
research agent or MCP server. A local index-inspection command is in scope;
full lexical/hybrid/reranking evaluation belongs to Phase 2. The eventual required
API endpoints remain part of the project, even though ingestion is terminal-driven
in this phase. Plot/equation interpretation is assessed during the pilot before
committing to implementation scope.

Use local compute without paid data acquisition/cloud compute initially. The
observed laptop GPU has 4 GiB VRAM and WSL exposes about 7.6 GiB RAM; remeasure
at execution time. P1-08 measured both parser candidates and selected the standard
pipeline for the pilot, with a review-only VLM path for suspicious tables.
Virtual filesystem free space is not proof of physical host capacity.

## Task checklist and dependencies

P1-01 is complete; implementation and verification are progressing under explicit delegation. Parser decisions and corpus acceptance evidence remain human-gated. Mark a task complete only with its listed evidence.
Use these IDs in commits or future issues; these rows are not published tickets.

| ID | Task | Depends on | Status |
| --- | --- | --- | --- |
| P1-01 | Entry gate and execution profiles | Phase 0 fixes | Complete (2026-09-23) |
| P1-02 | Typed ingestion contracts and configuration | P1-01 | Complete (serializable contracts, stable configuration/code identities, downstream invalidation and runtime validation tested; parser and model revisions are recorded; E5-small-v2 is the reversible ten-paper pilot choice, while the final embedding model remains open for Phase 2) |
| P1-03 | Safe schema evolution and persistence | P1-02 | Complete (migrations 001–012; empty-database and Phase 0 upgrade paths, failed-migration rollback, concurrent/repeated migrations, constraints and ingestion repositories pass isolated live tests) |
| P1-04 | Reproducible discovery and explainable shortlist | P1-02, P1-03 | Complete (2026-09-24; approved v1 manifest has 67 included, 47 excluded, reviewed coverage and documented discovery limits) |
| P1-05 | Paper/version identity and unresolved citations | P1-03, P1-04 | Complete (approved v1 import persisted 67 papers, 328 distinct authors, 114 source locations, 49 resolved citation edges and 1,501 unresolved endpoints; metadata outcomes recorded for all 1,166 distinct external targets: 954 found, 212 not found) |
| P1-06 | Acquisition and efficient artifact storage | P1-03, P1-05 | Complete for the ten-paper workflow; accepted ADR-0007 adds bounded Springer, version-pinned arXiv and Glasgow Eprints adapters with matching permission evidence and adapter tests. OpenAlex defaults remain CC BY/public domain; ten v1 PDFs acquired. |
| P1-07 | Human-verified 10-paper reference set | P1-04, P1-06 | Complete (2026-09-24; user confirmed all ten sampled prose passages, locations, table captions and selected values match the local PDFs; W4410600121 correction accepted) |
| P1-08 | Extraction comparison and quality decision | P1-07 | Complete (2026-09-24; 19 reviewed pages compared, Docling standard selected as automatic parser, Granite VLM restricted to review aid, thresholds and figure/equation scope recorded in ADR-0004 and comparison report) |
| P1-09 | Normalized evidence and chunking | P1-03, P1-08 | Complete for the corrected ten-paper draft (5,944 sections, 112 tables, 15,628 evidence units, 9,684 chunks); five table corrections across three papers and one figure reclassification; all eight flagged table checks passed. See the [pilot report](../reference/phase-1-full-extraction-pilot.md). |
| P1-10 | Embeddings, Qdrant indexing and rebuild | P1-09 | Complete for the reversible pilot (E5-small-v2 embedded all 9,684 chunks in 606 batches; expected and indexed counts reconciled; final model choice remains open for Phase 2 retrieval evaluation) |
| P1-11 | Runner, recovery and snapshot finalization | P1-02 through P1-10 | Complete for the local ten-paper workflow (start/status/resume/retry, draft inspection, index rebuild, and validation are tested; the draft validates with no issues and remains unfinalized only because the 100-paper minimum is unmet) |
| P1-12 | Operational visibility and storage controls | Across P1-03 through P1-11 | Complete for the pilot (11,587,433 source bytes; 2 GiB hard acquisition cap retained based on the full ten-paper footprint; row-size and process resource measurements recorded in the pilot report; disposable retention period remains open) |
| P1-13 | Verification suite and CI | Alongside every implementation task | Baseline revision `ebe1c41602b62c5934fbfe43e51ae765896e3e6e` passed hosted CI. The current worktree passes 188 tests (15 live), Ruff check/format, strict mypy, migration, `pip check`, `pip-audit` and Linux AMD64 Docker build. Hosted CI has not been rerun on this uncommitted tree. |
| P1-14 | 100-paper acceptance pilot and documentation | P1-01 through P1-13 | In progress under user delegation (10 v1 + 21 expansion + 51 cited + 18 cache-screen members; all 100 exact PDFs and persisted permissions checked; all extractions complete; 102 tables source-reviewed, one figure reclassified; 269/269 sampled unique numeric values present; snapshot in `research_phase1_review` validates and its 44,277 Qdrant evidence IDs reconcile; acceptance report and README runbook record the 10/100 profiles, local database target, recovery/retry, cleanup, rebuild, and benchmark reproduction; hosted CI on this worktree and snapshot finalization remain) |

The order describes completion dependencies, not a requirement to finish every
layer before exercising it. Introduce a minimal runner/checkpoint path with the
first persisted stage and expand it incrementally. Add tests and operational
records with each stage; P1-11 through P1-13 are consolidation gates, not permission
to defer reliability until the end.

## P1-01 — Entry gate and execution profiles

- Verify hosted CI against the committed Phase 0 fixes, not the earlier green revision.
- Record the starting code revision, environment lock and runtime versions.
- Measure usable RAM/VRAM and physical storage available to project artifacts.
- Define deterministic CI, 10-paper comparison and 100-paper pilot profiles.
- Give each profile explicit resource/request limits; keep live downloads and
  large-model execution outside ordinary CI.

Completion evidence: verified baseline, recorded hardware/runtime profile and
profile definitions. Reuse Phase 0 foundations rather than rebuilding them.

Learning: reproducible execution, configuration scope and interpreting CI evidence.

### P1-01 baseline and execution profiles

Verified 2026-09-23 against code revision
`d104e5607d90643fbd0dbb3119fbb7ace8c8e3fc`. Hosted
[CI run 35852371358](https://github.com/avsngh-git/RAGpipeline/actions/runs/35852371358)
completed successfully, including the locked environment, lint, formatting,
type checks, unit/API/service integration tests, migration, dependency checks
and Docker build.

The project lock is `environment-linux-64.lock`
(SHA-256 `7e72ec479c6820d8bad52ad8662f9496fedb2dfe41681b5ec1cf94926f2865ce`).
The local `sci_research_agent` environment uses Python 3.12.14, Conda 26.7.1,
Ruff 0.16.7, mypy 2.3.1 and pytest 9.1.1. Docker is 29.8.0 with Compose
5.5.1. CI uses PostgreSQL 16 and Qdrant 1.14.1.

Resource measurements are a dated snapshot and must be repeated before the
10-paper and 100-paper runs:

- Ubuntu 24.04 under WSL2: 7.6 GiB total RAM and 4.2 GiB available.
- RTX 3050 Laptop GPU: 4,096 MiB total VRAM and 3,964 MiB free.
- The Ubuntu WSL distribution is stored on `D:` (264.6 GiB free); Docker's WSL
  data is stored on `C:` (40.7 GiB free). The Linux view reports 949 GiB free
  in the WSL filesystem. These values do not set the later artifact storage cap.

| Profile | Input and request ceiling | Resource limits |
| --- | --- | --- |
| Deterministic CI | Synthetic or permitted small fixtures only. Zero OpenAlex, paper-download, or model inference/weight requests. Dependency installation and disposable service startup remain part of CI. | One CI job, CPU-only, no GPU or large-model execution. Use the locked Conda environment, PostgreSQL 16 and Qdrant 1.14.1. |
| 10-paper comparison | One reviewed manifest of at most 10 papers and at most one selected full-text version per paper. No recursive full-text acquisition from references. At most 10 selected-document acquisition work items; any HTTP retries count against a configured per-source total-request ceiling. | Local hardware only, one active ingestion process and one paper in flight. The measured WSL and GPU capacity above are the outer hardware envelope; P1-08 records the parser/model memory headroom measured on the reviewed pages. |
| 100-paper pilot | One approved manifest of at most 100 accepted full-text papers, one selected version per paper. No recursive full-text acquisition. At most 100 selected-document acquisition work items; retries count against configured per-source total-request ceilings. | Local hardware only, one active ingestion process and one paper in flight, with resumable progress. Set the numeric storage cap from the 10-paper footprint before scaling, as required by P1-12. |


### P1-01 pre-comparison resource recheck (2026-09-24)

Immediately before the ten-paper parser comparison, the host reported 7.6 GiB
RAM total and 3.7 GiB available. The RTX 3050 Laptop GPU reported 4,096 MiB
VRAM total and 3,964 MiB free. The project volume on D: had 265 GiB free; the
Docker data volume on C: had 37 GiB free. The WSL filesystem view had 949 GiB
free and is not a physical-capacity measure. The ten source PDFs occupy
11,587,433 bytes (12 MiB on disk); the 19-page standard comparison output was
1,018,293 bytes. Neither figure is the full 10-paper extraction footprint.
All external metadata and download traffic must use a configured page budget,
timeout, retry ceiling, per-source rate limit and total-request ceiling based on
verified source terms. Those exact per-source values and supported adapters are
resolved before live requests in P1-04/P1-06. The profile ceilings above bound
the workload without preselecting a source or parser.

### P1-01 pre-100 resource recheck (2026-09-25)

Immediately before the 100-paper pilot planning gate, WSL reported 7.6 GiB total
RAM and 4.6 GiB available. The RTX 3050 Laptop GPU reported 4,096 MiB total
VRAM and 3,964 MiB free. The project volume on D: had 244 GiB free; Docker's
C: volume had 29 GiB free. Docker reported 2.293 GB of images, 905.3 MB of
volumes and 1.898 GB of build cache. The WSL filesystem's 930 GiB available is
not physical host capacity. These are dated measurements; repeat them before
large-scale acquisition and extraction.


## P1-02 — Typed contracts and configuration

Introduce typed representations as their first use cases require them:
discovery candidates, external references, paper/document versions, artifacts,
extraction results, evidence units, snapshots, jobs, attempts and stage outcomes.
Keep application contracts independent of source, parser, database and model clients.

Validate serializable configuration for corpus queries/dates/language/exceptions,
supported sources, parser/model revisions, text/table chunking, embeddings/index
identity, retry/time limits, batches and storage limits. Separate secrets from
serializable configuration. Define stable identifiers for effective configuration,
record the code revision and define which changes invalidate downstream stages.

Completion evidence: invalid inputs fail clearly; configuration round-trips;
identical effective inputs have consistent identity; outputs reference the
configuration that produced them. Exact libraries and field layouts are implementation
choices, subject to existing architecture and measured needs.

Learning: dataclasses/Pydantic, enums, protocols, validation and serialization.

### P1-02 implementation evidence (2026-09-23)

Discovery, acquisition, chunking, embedding/index and per-stage configurations are
versioned, strictly validated, serializable and stably hashed. Stage identities define
downstream invalidation; extracted evidence records its effective configuration and
source artifact. Code provenance includes HEAD plus a digest of tracked and untracked
worktree changes. Runner contracts now validate document UUIDs, SHA-256 fingerprints,
JSON-compatible output/resource mappings, machine-readable failure categories and
boolean retryability, retry reasons and stage names. Unit coverage includes round
trips, stable IDs, invalidation, invalid inputs and dirty-worktree identity. Parser
and model revisions remain OPEN
values to populate after the human-reviewed pilot, not missing configuration support.

## P1-03 — Safe schema evolution and persistence

Add migrations; preserve the already-applied `001_initial.sql`. Support:

- normalized external paper identifiers and verified version relationships;
- artifact references, acquisition timestamps, permissions and checksums;
- extraction versions, evidence locations and structured tables;
- draft/finalized snapshots with selected versions and configurations;
- per-stage checkpoints, attempts, errors and output references;
- unresolved external citation endpoints without invented titles;
- index configuration and reconciliation status.

Make migration execution and version recording atomic where supported, with
protection against concurrent migration runs. Update integration tests that
currently assume only `001_initial`. Build repository operations and connection
lifecycle management appropriate to ingestion; the readiness probe is not an
application persistence layer.

Completion evidence: empty-database and Phase 0 upgrade paths pass; failed migrations
do not falsely record success; uniqueness and referential constraints have live,
isolated tests. Record material schema decisions through the project change process.

Learning: transactions, constraints, migrations, repositories and resource ownership.

### P1-03 implementation evidence (2026-09-23)

Migrations 001–012 apply atomically and repeatably under a PostgreSQL advisory lock.
Isolated PostgreSQL tests cover empty-database creation, Phase 0 upgrade, concurrent
and repeated runners, failed-migration rollback, uniqueness/referential constraints,
and paper, artifact, evidence, index, job and snapshot repositories. The standalone
CI migration command applied all 12 migrations to a fresh disposable database.
A later manifest-export attempt used the default `research` database and applied
migrations 002–012 there at 10:25 UTC on 2026-09-24. It found no discovery manifest
in that database and wrote no candidate records. Screening data remains in the
isolated `research_phase1_review` database.

## P1-04 — Discovery and explainable candidate selection

Implement configurable OpenAlex queries/filters, pagination, bounded requests,
provider throttling/backoff and resumable discovery. Preserve query/configuration,
retrieval timestamps and enough source metadata to explain a candidate's origin.
Source APIs can change: replayability comes from retained records, not a promise
that repeating today's query always returns the same future results.

Normalize identifiers, handle duplicates, and produce an explainable shortlist
with recorded selection signals. Export a reviewable manifest and preserve the
reviewer's inclusion/exclusion reasons, including explicit older-paper exceptions.
Keep negative and mixed findings. Review across all three coverage questions.

Evaluate shortlist relevance, coverage and bias against retained review decisions.
Report the evaluated sample and limitations; do not claim corpus-wide recall
without a suitable reference set. Improving selection is a Phase 1 deliverable;
a learned classifier is not required.

Completion evidence: discovery resumes correctly; candidate origin and selection
are inspectable; the pilot manifest is approved and versioned; selection weaknesses
and a follow-on improvement path are recorded.

Learning: HTTP clients, pagination, iterators, normalization and deterministic rules.


### P1-04 current OpenAlex verification (2026-09-23)

The adapter uses the official Works REST endpoint and the currently documented
query conventions. OpenAlex's [cursor paging guidance](https://help.openalex.org/api/paging/)
sets `per_page` to at most 100 and recommends cursor paging beyond the first
10,000 records; each query is additionally capped by this project's recorded
page and total-request limits. The official [filter reference](https://help.openalex.org/api/filtering/)
documents publication-year ranges and comma-combined filters. The official
[search reference](https://help.openalex.org/api/searching/) states that Works
search covers title, abstract and full text, and that search requests cost more
than list/filter calls. The [authentication/rate-limit reference](https://help.openalex.org/api/authentication/)
currently reports a 100-request/second hard ceiling and a free API key with a
larger daily budget. Since the current authentication and deprecation pages
are inconsistent about keyless use, the live adapter conservatively requires an
API key, sends it in the Authorization header, caps a run at 50 total HTTP
attempts, and waits at least one second between attempts. Live discovery remains
outside ordinary CI.

The verified documentation also warns not to use cursor paging to download the
entire Works dataset. This implementation pages only the configured search
queries, retains every fetched candidate and query origin, and records when a
configured page ceiling truncated results. It ranks the review shortlist using
OpenAlex's per-query result order; it does not automatically include or exclude
papers. Human decisions and coverage notes are required before manifest approval.

The `manifest report` command measures reviewer inclusion share over the selected
shortlist, breaks decisions down by query origin and retained selection signals, and
reports provider/page limits and query truncation. Origin counts can include the same
paper under more than one query. The report explicitly avoids treating shortlist inclusion share as corpus recall. It is tested against retained synthetic review data.

### P1-04 live discovery and review evidence (2026-09-24)

The bounded OpenAlex run completed in the isolated local `research_phase1_review`
database using the approved example configuration (configuration ID
`sha256:6aece0bed0aee0b1071fc4484efe56a733e8466bf7045281440d27ef57b56ac4`).
It saved 30 pages from three configured queries in 30 request attempts, below the
50-attempt ceiling, and reported `$0.03` API usage. The [current OpenAlex cost
reference](https://help.openalex.org/access/example-costs/) lists search calls at
`$0.001` each and `$1` daily free usage per key; at that rate the configured
50-attempt ceiling is at most `$0.05` if every attempt is billed as a search. No
full-text/content requests were made.

The run retained 2,334 unique candidates. Each query reached its 10-page/1,000-result
limit, so all three queries are marked truncated. Version 1 of the shortlist contains
114 unique candidates (105 with abstracts and 9 without); query-origin associations
overlap. On 2026-09-24, the user approved all candidate-level screening choices:
67 included and 47 excluded, including selective inclusion of directly relevant
reviews. The decisions and approved coverage assessment were imported into the
isolated `research_phase1_review` database, and manifest v1 was approved. Hybrid/dense
retrieval and reranking/latency are marked covered; chunking/citation is marked a gap
because direct citation-support evidence is limited in the candidate metadata. The
[approved manifest](../../manifests/phase1-discovery-v1.json),
[review decisions](../../manifests/phase1-discovery-v1-review.json),
[screening rationale](../../manifests/phase1-discovery-v1-screening-proposal.md),
and [review report](../../manifests/phase1-discovery-v1-report.json) are retained.
The manifest ID is `1d84a2eb-8379-45ee-923b-fd6dd219a103`. All queries were truncated
at the configured result limit; future selection improvements should add targeted
query variants and compare their retained candidates against this reviewed set. This
P1-04 discovery run made no full-text requests. Two separately authorized NC-ND
follow-ups were acquired on 2026-09-25 and remain unassociated; see the rights
preflight and acquisition inventory below.

#### Supplemental metadata-only discovery (2026-09-24)

Two targeted OpenAlex runs were completed in the isolated review database: citation/chunking and sparse/dense retrieval/reranking latency. Each used 20 requests and cost $0.02; neither run made full-text requests. Their 83- and 81-record draft shortlists contain 70 distinct new publications after cross-run and v1 DOI/title deduplication. Assistant title/abstract screening of those 70 records is recorded in the [screening review](../../manifests/phase1-discovery-expansion-review.json): 33 include and 37 exclude. The 33/37 decisions are finalized under the user’s explicit Phase 1 delegation; the v1 manifest remains unchanged until a new 100-paper acceptance set is assembled. The [source and rights preflight](../../manifests/phase1-discovery-expansion-rights-preflight.md) found exact-source CC BY terms for 23 proposed records and 10 records requiring follow-up. After the user's private noncommercial-use clarification and prior download authorization, two publisher versions with matching CC BY-NC-ND OpenAlex metadata and three exact, version-pinned arXiv preprints with CC BY-NC-ND/NC-SA terms were acquired under scoped configurations. One Glasgow accepted version was separately acquired under the user's personal-use scope. All six remain unassociated and private, and the global CC BY/public-domain default is unchanged. No OpenAlex cached route was available for the arXiv and Springer NC versions; the three arXiv files were acquired directly, while the Springer endpoint returned HTML. The fixed-host direct-source adapter in [accepted ADR-0007](../adr/0007-bounded-direct-source-pdf-downloads.md) supports Springer Nature, arXiv and Glasgow Eprints. arXiv URLs must pin a numbered version; each source/version still requires matching permission evidence. The user’s personal student-project decision supports private local personal/classroom-copy or text-mining use for the four source paths recorded in the rights preflight; W4384656680 was acquired under its personal-use terms, while three ACM/PMC follow-ups remain unacquired or unresolved. Six of the ten authorized follow-ups are now acquired. A Springer NC PDF route returned HTML rather than PDF and remains unresolved. The six downloaded files are unassociated with the accepted 100-paper set; see the [OpenAlex inventory](../../manifests/phase1-discovery-expansion-nc-acquisition.json), [arXiv inventory](../../manifests/phase1-discovery-expansion-arxiv-acquisition.json), and [Glasgow inventory](../../manifests/phase1-discovery-expansion-personal-use-acquisition.json). Raw v2/v3 manifests remain undecided drafts, and the approved v1 is unchanged.

#### Full-text source-path capacity check (updated 2026-09-25)

The 67 approved v1 titles had 28 cached-PDF plus license-metadata prefilter matches; those matches are not exact-version permission approvals. The 33 proposed additions have 23 source versions with primary-source CC BY statements and ten unresolved follow-ups. Together they yield at most 51 preliminary routes. Ten v1 PDFs are already stored, leaving 90 required files.

A no-network audit of the 954 found citation records removed discovery-candidate matches by OpenAlex ID, DOI, and normalized title. Two local title/abstract passes screened 192 distinct citation leads in the [citation-pool proposal](../../manifests/phase1-cited-work-screening-proposal.md) and [decision record](../../manifests/phase1-cited-work-screening-review.json): 55 include and 137 exclude, finalized under the user’s explicit Phase 1 delegation. Primary-source checks support 51 cached-PDF routes among those recommendations: 35 verified earlier, eight ACL Anthology papers verified in the supplemental pass, seven additional 2020 ACL Anthology records matched to their exact title and DOI, and one UvA-DARE final published-version PDF stating CC BY 4.0. Three recommendations still have unverified publisher terms, and one IRIS repository path has conflicting access metadata. Each still needs exact fetched-file/version, checksum, PDF-exception review, and persisted permission evidence before acquisition.

A separate local cache screen selected 80 of 448 direct-title-term matches outside discovery manifests and the cited-work pool. The [review](../../manifests/phase1-discovery-pool-screening-proposal.md) finalizes 43 include and 37 exclude under the user’s explicit Phase 1 delegation. All 43 have OpenAlex-reported CC BY and cached PDFs. Twenty-two are ACL Anthology published versions covered by its post-2016 CC BY 4.0 policy; two Springer, four MDPI, and one MIT Press TACL published-version page state CC BY 4.0; nine exact arXiv records link to CC BY 4.0 for their submitted versions; and four other publisher or repository records state CC BY 4.0, including the REIS published version in the ETH Zurich Research Collection. Three ACM-listed works have eligible arXiv preprint routes, but these do not establish ACM published-version terms. The Great Nugget Recall ACM version remains unverified, and its arXiv v1 license grants arXiv only a non-exclusive distribution right. Third-party material remains subject to credit-line exceptions and exact files have not been checked. No candidate PDFs were downloaded into the repository.

Across the 51 initial paths, 51 source-checked citation paths, and 42 source-policy-backed cache paths, there are at most 144 preliminary source routes among approved and delegated-screened titles. Ten PDFs remain associated with approved v1; five additional private NC PDFs are stored locally but unassociated and do not reduce the 90 accepted-paper gap. The screened titles are finalized under delegation. The accepted 100-paper membership decision selects 90 additions from these routes; it does not convert preliminary source checks into exact-file permission evidence. The one cache recommendation without a verified eligible source right does not add a route. Neither local title/abstract screen made OpenAlex API or content requests.

## P1-05 — Identity, versions and citations

Use reliable identifiers/metadata to associate document versions with one logical
paper. Prefer an eligible published version; use an eligible preprint when necessary.
Record the actual evidence version. Keep uncertain matches separate for review.

Retain real citation relationships with unresolved external identifiers before
full metadata exists. Enrich those records through bounded metadata requests;
never invent a title or automatically acquire referenced full text. Ensure the
schema supports these references without pretending they are complete papers.

Completion evidence: repeated inputs avoid duplicate logical records; version
selection is explainable; uncertain matches and unresolved references have tested,
explicit representations.

Learning: identity versus representation, normalization and referential integrity.

The CLI can now enrich unresolved OpenAlex citation endpoints with bounded,
per-identifier lookups. Found metadata and not-found outcomes are checkpointed
separately from `papers`, with the effective configuration and code revision.
The next invocation skips completed identifiers. Mocked and isolated persistence
tests cover this path; no live metadata request has been made.

### P1-05 implementation evidence (2026-09-23)

Paper imports from an approved manifest normalize OpenAlex and DOI identifiers,
persist author links and source-reported document locations/versions, add real
citation edges when both endpoints are represented, and otherwise retain the
external work ID as an unresolved citation. Re-import is idempotent and does not
invent a paper title. The preference helper deterministically favors the latest
permitted published representation, then an eligible preprint. Unit and isolated
PostgreSQL integration checks cover these paths. Bounded metadata enrichment is
implemented and checkpointed; live requests remain unrun.

### P1-05 approved-manifest import (2026-09-24)

Imported approved manifest
`1d84a2eb-8379-45ee-923b-fd6dd219a103` into collection
`dd7de0d9-0755-4a34-8d0b-e7d8ab6bce51` in the isolated local
`research_phase1_review` database. The import created 67 logical papers, linked
328 distinct authors, recorded 114 OpenAlex source locations as metadata-only,
and added 49 resolved citation edges. It retained 1,501 unresolved citation
endpoints across 1,166 distinct target identifiers; no imported paper lacked a
title. The manifest is approved, but no source PDF was acquired or selected.

Using the exact saved discovery configuration, the first resumable enrichment
batch checked 50 distinct unresolved targets: 48 returned metadata and 2 were
not found. Those outcomes are checkpointed separately from `papers`; 1,116
distinct target identifiers remain eligible for later bounded enrichment. The
official [OpenAlex example costs](https://help.openalex.org/access/example-costs/)
lists single-entity lookups by ID as free. The batch used 50 request attempts,
the configuration's one-second minimum interval, and its 50-attempt ceiling.
The review database is separate from the Compose `research` database.


### P1-05 citation metadata enrichment continuation (2026-09-24)

After the initial 50-target batch, the resumable OpenAlex command processed the
remaining 1,116 distinct targets in 23 bounded batches, using the same approved
configuration ID `sha256:6aece0bed0aee0b1071fc4484efe56a733e8466bf7045281440d27ef57b56ac4`.
Each batch was limited to 50 attempts and retained the configured one-second
minimum request interval. Across all 1,166 identifiers, 954 returned metadata and
212 returned not found; no target remains pending. Three recent not-found outcomes
were independently rechecked and returned HTTP 404. OpenAlex's rate-limit status
remained at $0.86 daily free balance, confirming singleton metadata requests used
no additional credits. Citation endpoints remain explicit unresolved records;
metadata lookup did not create papers or silently resolve citation edges.
## P1-06 — Acquisition and artifact storage

Build adapters for explicitly supported download sources. Verify current source
access terms and limits before acquisition. Record acquisition/indexing permission
evidence separately from public passage-display eligibility.

Enforce timeouts, bounded retries and streamed size limits. Validate destinations
and redirects to avoid unintended private/local-network requests. Validate returned
content instead of assuming an HTTP success contains a valid PDF. Detect incomplete,
invalid or oversized downloads. Publish completed artifacts atomically from temporary
files; retain checksums, source URLs, acquisition time and document-version links.

Keep unique originals once, share them across collections and compress extraction
outputs. Choose a local artifact root outside Git, configure its runtime mount,
and explicitly ignore generated data/model/index paths. Retain metadata-only records
separately from acquisition failures. Regenerate disposable page images when practical.

Completion evidence: interrupted writes never masquerade as complete artifacts;
repeated downloads avoid duplicate storage; source provenance resolves; retention
references protect shared artifacts.

Learning: streaming I/O, hashing, filesystem operations, atomic writes and cleanup.

### P1-06 source and adapter review (updated 2026-09-24)

The official [OpenAlex full-text documentation](https://help.openalex.org/access/fulltext/)
says its cached PDFs retain their original copyright and OpenAlex grants no
additional rights. For a specific work, it directs clients to
`best_oa_location.license`. The [locations documentation](https://help.openalex.org/data/locations/)
explains that licenses belong to individual hosted copies, while OpenAlex's own
cached content is exposed separately through `content_urls`. The [license
vocabulary](https://help.openalex.org/data/licenses/) distinguishes reusable
licenses from non-commercial, no-derivatives and catch-all labels. Accordingly,
the adapter checks both `has_content.pdf` and an explicit `best_oa_location.license`,
accepts only configured `cc-by` or `public-domain` values by default, and still
requires immutable human-reviewed storage and indexing permission evidence.
Passage-display eligibility is recorded separately. A PDF flag or URL alone does
not grant permission. The adapter uses the fixed OpenAlex content host, rejects
redirects, verifies the PDF response and byte limit, and publishes complete
checksum-addressed files atomically.

Current [OpenAlex example costs](https://help.openalex.org/access/example-costs/)
list cached PDF downloads at $10 per 1,000 calls ($0.01 per file) and a free daily
usage allowance of $1, enough for 100 files at that rate; single-entity metadata
lookups are free. On 2026-09-24, after the user's approval, ten cached PDFs were acquired under
recorded permission evidence for local storage and indexing. OpenAlex rate-limit
status reported $0.96 of free daily usage before the successful batch and $0.86
afterward; prepaid balance remained $0. An earlier failed local write incurred
$0.01; total content usage for this set was $0.11. No paid balance was used. The
ten-document ceiling was enforced.

arXiv's [bulk-access documentation](https://info.arxiv.org/help/bulk_data.html)
says its default non-exclusive license lets arXiv distribute an article but does
not let arXiv grant reuse rights to others. It says full-text indexes must link
back to arXiv and that per-submission license metadata is available through
OAI-PMH. The accepted [ADR-0007](../adr/0007-bounded-direct-source-pdf-downloads.md) enables bounded Springer Nature, explicitly version-pinned arXiv, and Glasgow Eprints PDF routes; exact-source permission evidence remains required.

Implementation evidence: the OpenAlex PDF adapter is mock-tested for explicit
permission, fixed-host requests, redirect rejection, retry/request/size bounds,
PDF validation and atomic storage. PostgreSQL integration tests verify immutable
review evidence and distinct storage, indexing and passage-display flags. The
OpenAlex content endpoint has now been used for ten approved published versions;
no arXiv full-text request has been made. Compose mounts the Git-ignored
`data/artifacts` directory into the API container at `/app/data/artifacts`, matching
the CLI's default root for host and container operations.

#### Candidate access preflight (2026-09-24)

The imported 67-paper manifest metadata reports an OpenAlex cached PDF for 42
works. The best OA license is `cc-by` for 33, `other-oa` for 2, `cc-by-nc-nd`
for 3, `cc-by-nc` for 2, and missing for 27. Twenty-eight works have both a
reported cached PDF and a license in the adapter's configured allowlist; all 28
are CC BY in this snapshot. Of 114 source locations, 61 have an explicit license
and 53 do not. These were metadata prefilters only: they did not establish per-document
permission or authorize acquisition. P1-07 records the later user approval and
the per-paper metadata and permission checks for the selected ten.

## P1-07 — Ten-paper reference set

Select representative papers across the agreed questions and difficult layouts.
Prepare human-verified samples from every paper before comparing approaches.
Include section/read-order samples, ordinary tables, merged headers, tables spanning
pages, numeric values and header associations, captions, units, footnotes and locations.

The assistant may prepare annotation files and comparison reports; a human must
verify selected evidence directly against the PDFs. Version the sampling rules,
annotations and corrections. Keep restricted full text outside Git.

Completion evidence: a versioned reference set with explicit checked coverage and
expected results independent of parser outputs. Record sample counts and limitations;
this is not a claim of exhaustive checking of every page or cell.

The [ten-paper proposal](../../manifests/phase1-discovery-v1-pdf-reference-proposal.md)
selects approved-manifest records whose imported metadata reported a cached PDF,
a CC BY best-open-access license and a published version. The user approved the
exact sample for local storage and indexing on 2026-09-24; public passage display
remains disabled. Immediately before each content request, all ten works still
reported cached PDFs, CC BY licenses and published-version records. The ten PDFs
were acquired into Git-ignored data/artifacts, totaling 11,587,433 bytes.
Checksums and immutable permission evidence are recorded in the
[acquisition inventory](../../manifests/phase1-discovery-v1-pdf-acquisition.json).
The free daily balance fell from $0.96 to $0.86, with no prepaid balance used.
An earlier failed storage attempt cost $0.01 but left no file; total Phase 1
content usage was $0.11. After the reviewer flagged a metric-label mismatch in
W4410600121, I corrected the local review packet: the Naive RAG / SQuAD row maps
0.736 to K-Precision, 0.945 to FS and 0.666 to ARS. On 2026-09-24 the user
confirmed that all ten sampled prose passages and table evidence, including
their PDF locations, match the local PDFs. The correction is accepted and all
ten annotations record the explicit confirmation. The [local review packet](../../local-reference/phase1-discovery-v1/review-draft.md)
and [compact review index](../../manifests/phase1-discovery-v1-pdf-review.md)
retain the user-confirmed outcome. This verifies the selected samples, not every
page or cell in the ten papers.

#### P1-07 local PDF title and location check (2026-09-24)

The user confirmed that the saved PDF titles match the approved papers and updated
the page locators in the [review index](../../manifests/phase1-discovery-v1-pdf-review.md)
after checking the local files. I prepared a short draft prose/table sample for each
paper in the ignored local-reference directory. Following the W4410600121 label
correction, the user confirmed that all ten prose/table samples and their locations
match the PDFs. This completes P1-07 and opens P1-08. The resulting reference set
is limited to these ten short samples and is not an exhaustive page/cell audit.
Learning: reference data, annotation consistency, sampling and evaluation bias.

## P1-08 — Extraction comparison and decision

Compare structured document conversion with a local vision-model approach using
pinned configurations on the reference set. Docling pipelines are candidates,
not selected dependencies. Provider-parsed text may also be evaluated but must
meet the same evidence requirements.

Measure text omissions/read-order errors; table values, structure and contextual
accuracy; source-location correctness; runtime; peak RAM/VRAM; artifact sizes;
and failure/recovery behavior. Preserve figures/captions/equation regions where
available, assess interpretation capability, and explicitly decide its phase scope.

Record a justified pipeline or combination/fallback decision. Do not assume a
model fits the laptop or that structured output guarantees accuracy. Set numerical
acceptance criteria after this assessment and before judging the 100-paper run;
record their definitions, denominators and checked sample.

Completion evidence: comparison artifacts, reproducible commands/configurations,
resource measurements, accepted extraction decision and quality thresholds.

Learning: adapters, controlled experiments, measurement and error analysis.

### P1-08 comparison and decision evidence (2026-09-24)

The user confirmed all ten independent prose/table reference samples and their PDF
locations. The comparison then processed only the 19 annotated pages from those ten
PDFs (280 PDF pages total). Both Docling pipelines completed all 19 pages without
conversion errors. Docling standard achieved 100% ordered-token coverage over the
annotated prose, 100% page provenance over 366 located elements and 98% mean
caption coverage. It found 57 of 66 annotated numeric values (86.4% weighted).
Granite-Docling achieved the same prose and page-location scores, 88% mean caption
coverage and 60/66 numeric values (90.9% weighted), but took 908.855 seconds versus
30.437 seconds. The local standard run peaked at 2,937,028,608 bytes process RSS
and 1,868,562,432 bytes CUDA reserved; VLM peaked at 2,317,397,616 bytes RSS and
1,023,410,176 bytes CUDA reserved.

W4404782883 is the material failure case. The standard pipeline preserved a 26×8
table with two header rows and marked 30 cells as column headers, but found only
3/12 selected numeric values. VLM found 11/12, but returned a 25×11 grid with no
header-marked cells. Its different grid and missing header relationships make an
automatic cell merge unsafe. The standard extractor is selected as the automatic
pilot parser; VLM output is diagnostic only for tables meeting the measured
sparse/multi-header rule. All such tables need human review before verified use.
The heuristic (at least two consecutive column-header rows and at least 20% blank
grid positions) flagged one of ten reference tables. It is a pilot heuristic, not
a guarantee of defect detection.

Numerical acceptance thresholds and their denominators are in the
[comparison report](../reference/phase-1-extraction-comparison.md). Plot/chart
interpretation is out of Phase 1 scope. Preserve available figure captions,
formula/equation text and source locations; keep the permitted PDF as the image
source. Accuracy for figure/equation regions was not measured because the
human-labeled samples do not include expected outputs for those regions. The
reviewed tables are each on one page, so multi-page table behavior remains an
explicit coverage gap.

The runnable adapter pins Docling 2.130.0 and the selected model revisions,
records resolved pipeline options/dependency versions/OCR weight hashes, and was
translated against all 19 standard-pipeline page outputs into 292 source-located
text blocks and 11 source-located tables. The comparison report, implementation
decision and consequences are recorded in
[ADR-0004](../adr/0004-phase1-pdf-extraction.md).

## P1-09 — Evidence normalization and chunking

Define source-location conventions: actual document version, page numbering,
coordinate system when available and offsets into retained normalized text.
Represent missing location detail explicitly rather than fabricate coordinates.

Respect section boundaries for prose. Preserve table cells and header relationships;
include captions, units and footnotes in searchable context. Split large tables into
row groups with relevant headers repeated, linked to the complete structured table.
Keep derived searchable text linked to retained evidence, not only model summaries.

Evidence identities must distinguish changed documents/extractions while remaining
stable across equivalent retries. A results-table validation failure blocks successful
ingestion of the paper until resolved. Keep usable intermediate outputs for retries
or reviewed corrections with provenance. Any eventual exclusion is a recorded
selection decision, not silent quality filtering.

Completion evidence: inspectable source-linked evidence, repeatability checks,
section/table boundary tests and a versioned chunking configuration.

Learning: immutable identities, structured data transformations and boundary cases.

## P1-10 — Embeddings, index integrity and rebuild

Choose an initial locally runnable embedding model through pilot measurements;
full retrieval-quality comparison remains Phase 2. Record model/revision, dimensions,
preprocessing, input limits and batching configuration.

Implement bounded embedding batches and repeatable Qdrant upserts. Payloads must
resolve evidence, paper, document version, configuration, collection/snapshot and
filterable metadata to authoritative records. Separate incompatible embedding/index
configurations. Define reconciliation after partial cross-store writes; do not
pretend PostgreSQL and Qdrant share an atomic transaction.

Provide index validation/rebuild from retained evidence and configuration, plus a
small local inspection/query command. Verify IDs, counts and source resolution;
bit-identical model outputs are not assumed unless the runtime supports that claim.

Completion evidence: retry-safe upserts, partial-write recovery, configuration mismatch
checks and a successful rebuild with expected evidence membership and provenance.

Learning: embeddings as derived data, batching, adapters and cross-store consistency.

## P1-11 — Runner, recovery and snapshot lifecycle

Provide terminal operations for start, status, resume, targeted retry, draft-evidence
inspection, validation/finalization, index rebuild, storage inspection and cleanup preview.
Choose command spelling during implementation and document it; these names are capabilities,
not a locked CLI syntax.

Build the runner over reusable application services. Allow one active ingestion
process initially with ownership/concurrent-start protection and explicit crash recovery.
Bound download concurrency and control extraction/embedding batches. The process stops
when terminated; persisted progress supports resumption rather than background execution.

Checkpoint successful stages and output fingerprints. Invalidate only affected
downstream work on configuration/input changes. Continue other papers after
paper-specific errors; pause on shared database/storage failures. Preserve stage and
reason for targeted retries, with explicit pending/partial/completed/failed/skipped outcomes.

Draft snapshots are inspectable/testable. Finalize explicitly only after validating
fixed membership, selected document/extraction versions, effective configurations
and index integrity. Normal research consumes finalized snapshots. New evidence
or configuration changes produce a new snapshot rather than silently altering one
used by retained runs. A smaller valid snapshot does not satisfy the 100-paper target.

Completion evidence: interruption/resume, targeted retry, duplicate-start rejection,
stale ownership recovery, finalization rejection and immutable finalized references
are demonstrated by tests.

Learning: state machines, CLI design, ownership and idempotency.

## P1-12 — Operational visibility and storage controls

Record job/document/stage IDs, durations, counts, retries, failure categories,
configuration IDs and resource measurements. Keep availability (metadata-only/full
text), processing outcome and snapshot lifecycle distinct. Avoid logging secrets
or disallowed source content.

Measure the 10-paper footprint; configure a cap before scaling. Pause new acquisition
at the limit. Clean temporary/disposable outputs promptly; protect artifacts shared
across collections or referenced by retained snapshots/runs. Make cleanup inspectable
and retirement explicit. Test interrupted cleanup and accounting consistency.

Completion evidence: failures can be explained from recorded events, the pipeline
respects resource limits, and cleanup preserves shared/retained evidence.

Learning: structured observability, accounting, retention and operational diagnostics.

### Initial component-level P1-09 through P1-12 evidence (2026-09-23)

This section records the component implementation before the full ten-paper run;
the measured workflow outcome is recorded in the subsequent pilot report.

The local contracts preserve PDF page indices separately from printed labels,
normalized bounding boxes, section text, table cells/header references, units,
footnotes and deterministic text/table-row-group identities. Extraction output
is stored transactionally against its effective configuration and exact reviewed
source artifact. Replaying identical output is idempotent; changed output under the
same configuration is rejected.

Qdrant uses a versioned model-neutral configuration. The embedding adapter receives
bounded text batches; model name/revision, preprocessing revision, vector dimensions,
distance and collection identity are recorded. A collection is assigned to one
embedding configuration. Rebuild removes only the target snapshot's points, then
reconciles exact evidence IDs and counts against PostgreSQL. Permission checks use
the same artifact association recorded by extraction. No embedding model has been
selected or loaded.

The adapter-neutral runner records one active lease, stage attempts, output fingerprints,
resource measurements and machine-readable failure categories. Free-form exception
text is omitted from persisted error summaries so parser messages cannot leak source
passages or credentials; the runner exposes only a category-only failure, including
when it is cancelled with a caller-supplied message. Live persistence tests verify
these paths. It skips matching completed stages,
continues after paper-specific failures, stops on shared failures, renews active leases,
and records cancellation as a retryable failed attempt. Targeted retries name both the
document and starting stage and persist the operator's reason. Stale leases close running
attempts as retryable and can be claimed again. Snapshot inspection lists selected
versions, statuses, permission flags and evidence counts without exposing source text.
Validation requires the reviewed source-artifact permission, usable extraction/chunks,
a ready index and matching PostgreSQL/Qdrant evidence-ID fingerprints before finalization.
Finalized membership and snapshot metadata are database-immutable. CLI operations expose
snapshot inspection/validation/finalization, job status, index inspection, storage
inspection, cleanup preview and explicit age-bounded cleanup. Cleanup blocks while a job
is active, preserves referenced artifacts and retries safely after interrupted deletion.
The local `snapshots evidence` command previews evidence from draft snapshots only; it
filters by exact source-artifact storage permission and bounds text and table output.
End-to-end `jobs start/resume`, targeted retry and `index rebuild` CLI commands await
stage wiring to the selected parser and embedding adapter; the adapter-neutral runner
and rebuild library remain available and tested.

The artifact store serializes writers per store instance, publishes PDFs atomically,
reports physical/configured capacity, and lists unregistered or unreferenced files
without deleting them. The ten source PDFs use 11,587,433 bytes.

### P1-09 through P1-12 full ten-paper pilot evidence (2026-09-24)

The initial ten-paper run processed ten papers with no failures and produced
5,944 sections, 113 tables, 15,627 evidence units and 9,683 chunks. Subsequent
source-linked immutable corrections fixed five tables across three papers and
reclassified one figure in a fourth paper. All eight flagged tables now pass. The
corrected draft has 5,944 sections, 112 tables, 15,628 evidence units and 9,684
chunks, with no pending review issues; see the [pilot
report](../reference/phase-1-full-extraction-pilot.md) for extraction lineage.

The reversible E5-small-v2 configuration was rebuilt after correction. PostgreSQL
and Qdrant both report 9,684 chunks across 606 batches, and ten-paper snapshot
validation returns no issues. The snapshot remains a draft until the 100-paper
acceptance gate is met. The final model choice stays open for Phase 2.

The source-artifact store contains 11,587,433 bytes against the configured
2,147,483,648-byte cap. Retain this 2 GiB hard cap for the 100-paper pilot: the
simple tenfold source-size projection is about 115.9 MB, or 18.5 times below the
cap. The estimate is based on ten papers and does not guarantee a later corpus will
fit. New acquisition stops at the limit. Disposable-artifact retention remains
open. Summed `pg_column_size` across selected evidence rows is 29,227,416 bytes;
this excludes indexes, WAL and database overhead. Per-paper processing summed to
845.403 seconds, and the processor high-water RSS was 5,099,646,976 bytes.

## P1-13 — Verification suite and CI

Build tests alongside each behavior. Use small synthetic/permitted fixtures,
isolated PostgreSQL/Qdrant services and deterministic substitutes for network/model
boundaries in ordinary CI. Run real-model quality/performance experiments separately.

| Area | Required cases |
| --- | --- |
| Configuration | Validation, serialization, stable configuration identity, stage invalidation |
| Discovery | Pagination, duplicate results, interruption, malformed metadata, throttling |
| Acquisition | Interrupted/atomic writes, invalid content, streamed size bounds, unsafe redirects, checksum reuse |
| Identity | Published/preprint preference, uncertain matches, unresolved citations |
| Evidence | Missing content, incorrect table associations, source locations, chunk boundaries |
| Persistence | Migration failure/retry, constraints, stage transitions, snapshot immutability |
| Indexing | Partial writes, repeat upserts, incompatible configuration, orphan detection, rebuild |
| Operations | Cancellation, targeted retries, concurrent starts, storage exhaustion, safe cleanup |
| Security | Secret-safe logs, untrusted document handling and download destination controls |

Confirm public test boundaries with the user when using the TDD skill. Expectations
must describe behavior rather than repeat implementation logic. Run hosted CI on the
actual completed revision, retaining GPU/network-heavy benchmarks as separate evidence.

Completion evidence: relevant cases pass in the documented small profile and hosted
CI, with reference/model evaluation results linked independently.

### P1-13 baseline verification (2026-09-25)

The full suite passed on code revision `ebe1c41602b62c5934fbfe43e51ae765896e3e6e`: **162 passed in 3.76 seconds**,
including all 15 live PostgreSQL/Qdrant integration checks. The disposable
`research_test` database was created for the run and dropped afterward; the
persistent `research` and `research_phase1_review` databases were left in place.
The approved `phase1-e5-small-v2` Qdrant collection remained green with 9,683 points.

On the same code/test tree, `ruff check .`, `ruff format --check .` (91 files),
strict mypy (37 source files), `pip check`, and `pip-audit --skip-editable` passed.
The audit found no known vulnerabilities and excluded the two editable local
distributions. The `linux/amd64` Docker build passed and its temporary image tag
was removed. [hosted CI run 36053054222](https://github.com/avsngh-git/RAGpipeline/actions/runs/36053054222) completed successfully on the exact same revision, including
lint, formatting, typing, unit/API/live-service tests, migration, dependency
checks, and Docker build. That hosted evidence applies to the baseline revision only. The current worktree adds the direct-source adapter, its tests, acquisitions and review records; hosted CI and the Docker build have not been rerun on this uncommitted revision.


### Follow-up adapter verification (2026-09-25)

The adapter worktree passed **177 tests in 3.95 seconds**, including all 15 live
PostgreSQL/Qdrant checks. The disposable `research_test` database was created and
dropped; `research` and `research_phase1_review` were not modified by the suite.
Full-project Ruff check, format (94 files), strict mypy (37 source files),
`pip check`, and `pip-audit --skip-editable` passed. A `linux/amd64` Docker build
also passed under a temporary image tag, which was removed after the build. Hosted
CI remains verified only on the baseline commit described above; it has not run on
this uncommitted revision.

### Correction workflow and arXiv route verification (2026-09-25)

At that checkpoint, the correction/adapter worktree passed **182 tests in 3.60 seconds**,
including all 15 live PostgreSQL/Qdrant checks, using a fresh temporary
PostgreSQL service and the configured Qdrant test service. Ruff check, format
(96 files), strict mypy (38 source files), and `pip check` passed. The dependency
audit found no known vulnerabilities after restoring local setuptools to the
84.0.0 version in the project lock. The Linux AMD64 Docker build passed; its
temporary image tag was removed. Hosted CI remains verified only on the baseline
revision above. A preliminary run against the persistent `research_test` database
hit duplicate-key fixture collisions, so local integration runs should use a
fresh disposable PostgreSQL service, as CI does.

### Final current-worktree verification (2026-09-25)

After the latest source fixes, the full suite passed **188 tests in 3.59 seconds**,
including all 15 live PostgreSQL/Qdrant checks, against a freshly recreated
`research_test` database in the disposable PostgreSQL container. Ruff check passed;
Ruff format check passed for 92 files; strict mypy passed across 40 source files.
The CI migration step, `pip check`, and `pip-audit --skip-editable` passed, with no
known vulnerabilities. The CI `linux/amd64` Docker build passed using a unique
temporary image tag, which was removed afterward. The disposable PostgreSQL
container was stopped after verification. Hosted CI remains verified only on the
baseline revision; this worktree has not been pushed or run by hosted CI.

## P1-14 — Hundred-paper acceptance and documentation

Freeze the selected configuration and reviewed manifest, then run the full pipeline.
Use automated integrity checks for every paper and a documented manual sample for
quality assessment. Report precisely what was checked; do not imply every table cell
was manually verified.

The report must include discovery/shortlist/selection/exclusion counts; coverage
across the three questions; source and published/preprint distribution; metadata-only,
failed, skipped, partial and completed counts; extraction metrics/sample sizes;
processing time/RAM/VRAM/storage/retries; and integrity/rebuild outcomes. Preserve
reasons for any replacement or exclusion. Only accepted full-text papers count toward 100.

Document setup, permitted source access/credentials, execution profiles, CLI usage,
interruption/retry, configuration changes, cleanup, rebuild and benchmark reproduction.
Update README, the learning handoff and source of truth with actual outcomes.

Completion evidence: accepted report and finalized 100-paper snapshot with usable
text/table evidence, quality gates satisfied, all indexed sources resolvable,
recovery/rebuild demonstrated, storage bounded and CI passing. State limitations
and Phase 2 inputs without claiming later retrieval or generation capabilities.

## Explicitly open decisions and their decision points

| Decision | Resolve when |
| --- | --- |
| Exact source adapters, access limits and per-source permissions | Before acquiring the reference set; inspect current official terms/docs |
| Exact schema, artifact paths and CLI/library choices | At the corresponding implementation task; record material decisions |
| Parser/local vision model and fallback | Ten-paper comparison |
| Numerical quality thresholds and manual sampling protocol | After reference assessment, before 100-paper acceptance |
| Chunk sizes/table row-group sizes and initial embedding model | Pilot measurements and recorded configuration |
| Storage cap and disposable retention periods | Ten-paper footprint assessment, before scaling |
| Plot/equation interpretation scope | Pilot assessment |
| More advanced selection/classifier and expansion criteria | Review initial shortlist results; beyond the required explainable baseline |
| Background scheduling and ingestion API integration | Later operational need; preserve the eventual API contract |

## Research starting points

Verify current terms/model requirements when the relevant task is reached:

- [OpenAlex full text](https://help.openalex.org/access/fulltext/)
- [arXiv bulk access](https://info.arxiv.org/help/bulk_data.html)
- [Docling document model](https://docling-project.github.io/docling/concepts/docling_document/)
- [Docling vision pipelines](https://docling-project.github.io/docling/usage/vision_models/)
