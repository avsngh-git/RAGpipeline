# Scientific Research Platform

An installable Python project for a scientific literature research platform.

## Project status

Phase 0 and the Phase 1 corpus milestone are complete. The accepted 100-paper
snapshot is finalized. Phase 1 remediation passed [hosted CI
36238052340](https://github.com/avsngh-git/RAGpipeline/actions/runs/36238052340)
on revision `d28e1adc299d6199774c78a2d63cb3eb0870d5ab`; see the
[audit closeout](docs/reviews/phase-1-completion-audit-2026-09-26.md) and
[corpus acceptance report](docs/reference/phase-1-100-paper-acceptance-report.md).

**Phase 2 planning is approved; P2-01/P2-02 and the P2-03.1 inventory are
complete. The next step is canonical retrieval-profile design (P2-03.2).** See the [entry report](docs/reviews/phase-2-entry-check.md) and the
[detailed retrieval/evaluation roadmap](docs/plans/phase-2-retrieval-evaluation.md),
which contains 20 tasks with numbered substeps, dependencies and completion gates.
The [agent handoff](docs/plans/phase-2-agent-handoff.md) defines the next step;
benchmark work follows the [evaluation protocol](docs/plans/phase-2-evaluation-protocol.md).
Implementation and source review are delegated, with new judgments labeled
assistant-reviewed.

## Development environment

This project uses Conda as its development dependency manager.

Create the environment from the human-maintained specification:

```bash
conda env create --file environment.yaml
conda activate sci_research_agent
python -m pip install --no-build-isolation --no-deps -e .
```

The editable installation makes the local `src/` package importable while
keeping source changes immediately available to the environment.

Run the project checks from the repository root:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
```

The integration tests skip unless RESEARCH_PLATFORM_TEST_DATABASE_URL and
RESEARCH_PLATFORM_TEST_QDRANT_URL point to disposable services. The
PostgreSQL URL must use a dedicated database named research_test; tests apply
migrations and enforce constraints. The Qdrant test creates and removes a
temporary collection. CI supplies fresh service containers for these tests.

## Locked Linux environment

`environment-linux-64.lock` is an exact Conda package lock for Linux x86-64.
Use it when reproducing the currently tested Linux environment:

```bash
conda create \
  --name sci_research_agent_linux \
  --file environment-linux-64.lock

conda run -n sci_research_agent_linux \
  python -m pip install --no-build-isolation --no-deps -e .
```

The local package is installed separately because the lock file contains the
Conda environment packages, not the repository's editable source tree.

## Application configuration

`research_platform.config.Settings` reads configuration from process
environment variables and validates it when a settings object is created.
Supported variables are:

- `RESEARCH_PLATFORM_ENVIRONMENT`: `development`, `test`, or `production`.
- `RESEARCH_PLATFORM_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or
  `CRITICAL`.
- `RESEARCH_PLATFORM_DATABASE_URL`: a PostgreSQL connection URL.
- `RESEARCH_PLATFORM_QDRANT_URL`: an HTTP or HTTPS Qdrant URL.
- `RESEARCH_PLATFORM_DEPENDENCY_TIMEOUT_SECONDS`: positive timeout for readiness
  checks.
- `OPENALEX_API_KEY`: secret used by explicitly invoked discovery/acquisition
  commands; it is never part of the serialized ingestion configuration.

`.env.example` documents safe local-development values. It is not loaded
automatically by the standard library configuration code; copy it to `.env`
and export those values in the shell, or provide the variables through Docker
Compose. `.env` is ignored by Git and must contain any real credentials.

Invalid values raise `ValueError` during `Settings()` construction so an
application fails at startup with a clear configuration error.

## Run the API

Start the development server with Uvicorn:

```bash
python -m uvicorn research_platform.api:create_app \
  --factory \
  --reload
```

Check process liveness:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Logging and errors

The API assigns every HTTP request an `X-Request-ID`. A caller-provided ID is
preserved when it is non-empty and reasonably bounded; otherwise the API
generates a UUID. The ID is returned in response headers and error bodies, and
is attached to request logs.

Application logs are emitted as JSON with timestamps, levels, logger names,
request IDs, and safe HTTP metadata. Expected failures can raise `AppError`
and return a structured response containing an error code, message, and
request ID. Unexpected failures return a generic `internal_error` response.
Exception diagnostics retain the exception type and frame locations while
omitting exception messages and traceback source text.

## Local services and migrations

Start PostgreSQL, Qdrant, and the API together:

```bash
docker compose up --build
```

The services use named volumes so ordinary restarts preserve local data.
Verify liveness and dependency readiness separately:

```bash
curl http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
```

Apply the versioned PostgreSQL schema from the host environment:

```bash
conda activate sci_research_agent
python scripts/migrate.py
```

The migration runner records applied versions in `schema_migrations` and is
safe to run again. The Qdrant index remains a derived store and is not part
of the relational migration.


## Phase 1 discovery and manifest review

The terminal discovery command uses OpenAlex Works search with a versioned
JSON configuration, cursor checkpoints, one request at a time, a 50-request
per-run ceiling and bounded retries. The API key is read from `OPENALEX_API_KEY`
(or the ignored project `.env` file); it is never included in the serialized
configuration or request URL. Ordinary tests use mocked source responses and
make no OpenAlex requests.

```bash
cp .env.example .env
# Add your OpenAlex key to .env, then:
conda activate sci_research_agent
python -m research_platform.ingestion.cli discover \
  --config configs/phase1-discovery.example.json
```

The command prints a discovery run ID. Resume an interrupted run with the same
configuration:

```bash
python -m research_platform.ingestion.cli discover \
  --config configs/phase1-discovery.example.json --resume RUN_ID
```

Prepare and export the explainable shortlist, edit each decision/reason and the
three coverage reviews, then import it and explicitly approve it:

```bash
python -m research_platform.ingestion.cli manifest prepare \
  --run-id RUN_ID --version 1 --per-query-limit 50
mkdir -p data/manifests
python -m research_platform.ingestion.cli manifest export \
  --manifest-id MANIFEST_ID --output data/manifests/phase1-v1.json
# Edit phase1-v1.json and fill all decisions and coverage notes.
python -m research_platform.ingestion.cli manifest import \
  --manifest-id MANIFEST_ID --input data/manifests/phase1-v1.json
python -m research_platform.ingestion.cli manifest approve \
  --manifest-id MANIFEST_ID --reviewer "Your name"
```

Approval is an explicit human action. It requires a reason for every shortlist
decision and a covered/gap note for each approved coverage question. PostgreSQL
prevents later edits to an approved manifest. Discovery records the query origin,
OpenAlex rank, provider metadata and explicit older-paper exceptions; its
shortlist is a review aid, not an inclusion classifier. After review, generate a
report with candidate decisions, per-query yield, coverage notes, selection-signal
breakdowns, request limits and any truncated queries. Its inclusion share describes
the reviewed shortlist only; it does not estimate corpus recall.

```bash
research-ingest manifest report \
  --manifest-id MANIFEST_ID --output data/manifests/phase1-review-report.json
```

After approval and import, unresolved citation IDs can be enriched with a separate
bounded metadata lookup. The command saves found/not-found results by external ID
without creating placeholder paper rows. Each request uses the same configured
request and retry limits:

```bash
research-ingest citations enrich \
  --config configs/phase1-discovery.example.json --limit 20
```

This command makes live OpenAlex metadata requests. Tests use mocked responses and
do not call OpenAlex. Full-text download is separate from discovery and citation
enrichment. The accepted adapters cover OpenAlex content, Springer Nature,
version-pinned arXiv, and Glasgow Eprints. Exact hosts, request bounds, and
source-specific permission evidence are recorded in
[ADR-0007](docs/adr/0007-bounded-direct-source-pdf-downloads.md). The 100 selected
files passed their individual version, checksum, storage, and indexing checks;
six other privately stored follow-up PDFs remain unassociated with the accepted set.

## Phase 1 evidence, indexing and operations

The API container and host CLI share the default artifact root. Compose bind
mounts the Git-ignored `data/artifacts` directory at `/app/data/artifacts` inside
the API container, so downloaded source PDFs persist across container recreation.

The approved ten-paper extraction and indexing pilot is recorded in the
[full-pilot report](docs/reference/phase-1-full-extraction-pilot.md). After
source-linked corrections and figure reclassification, all eight flagged-table
checks passed. Its snapshot remains a draft because it is below the 100-paper
acceptance minimum, not because a table review is pending.

The ingestion CLI can create and edit draft snapshots, validate their selected
versions and permissions, and finalize them under a named reviewer. Finalization
checks the 100-paper minimum by default, exact extraction source-artifact
permission, usable chunk membership, Qdrant count and the fingerprint of the
indexed evidence IDs. Use `--minimum-papers 10` only for a separately reviewed
10-paper pilot snapshot; it does not meet the Phase 1 acceptance target.

```bash
research-ingest snapshots create \
  --name phase1-pilot \
  --configuration data/manifests/snapshot-config.json
research-ingest snapshots add \
  --snapshot-id SNAPSHOT_ID \
  --paper-id PAPER_ID \
  --document-id DOCUMENT_UUID \
  --extraction-id EXTRACTION_UUID \
  --selection-reason "Approved manifest inclusion"
research-ingest snapshots inspect --snapshot-id SNAPSHOT_ID
research-ingest snapshots evidence --snapshot-id SNAPSHOT_ID --limit 20
research-ingest snapshots validate --snapshot-id SNAPSHOT_ID
research-ingest snapshots finalize \
  --snapshot-id SNAPSHOT_ID --reviewer "Your name"
research-ingest jobs status --job-id JOB_UUID
```

The evidence command prints a bounded local preview from a draft snapshot. It
accepts a limit from 1 to 100 for each type, truncates text previews at 2,000
characters, and shows at most 50 cells per table with cell text clipped at 500
characters. The output reports when results are clipped.
Evidence appears only when the exact extraction source artifact has reviewed
storage permission. Public passage display remains disabled. Document availability
(`metadata_only` or `acquired`) is recorded separately from per-job processing
outcomes and snapshot lifecycle.

The snapshot configuration JSON includes the chosen `index_configuration_id`.
For the Phase 1 pilot, use the reversible E5-small-v2 configuration recorded in
[ADR-0005](docs/adr/0005-phase1-embedding-pilot.md). The final model choice remains
open until Phase 2 retrieval-quality evaluation. Install the optional parser and
embedding dependencies only in the local ingestion environment; ordinary CI does
not download their model weights.

For a new draft, add the approved paper/document pairs before starting
extraction. The CLI records `10-paper-comparison` for up to 10 members. For an
exact 100-member draft it records `100-paper-pilot` and requires the approved
membership decision, source-route review, and source-content review. The acceptance
run is already complete; starting another job against its snapshot would repeat
extraction work. The review inputs live under Git-ignored `manifests/` and
`local-reference/` paths and are available only in the local project workspace.

A 10-paper comparison job uses:

```bash
research-ingest jobs start \
  --snapshot-id SNAPSHOT_ID \
  --chunking-configuration configs/phase1-e5-small-v2-chunking.example.json \
  --artifact-root data/artifacts
```

The accepted 100-paper snapshot is in the isolated `research_phase1_review`
database. Export its URL before running 100-paper snapshot or job commands; the
Compose default `research` database does not contain the accepted snapshot. The
membership, selected-document map, and source review files are Git-ignored local
review data, not files available from a clean checkout.

```bash
export RESEARCH_PLATFORM_DATABASE_URL=postgresql://research:research@localhost:5432/research_phase1_review
```

To create a fresh 100-paper run, create a separate membership-bound draft and add
the selected documents. This does not modify the accepted snapshot and will repeat
the extraction workload:

```bash
research-ingest snapshots create \
  --name phase1-100-reproduction \
  --configuration local-reference/phase1-100/snapshot-configuration.json
research-ingest snapshots add-membership \
  --snapshot-id NEW_SNAPSHOT_ID \
  --decision manifests/phase1-100-paper-membership-decision.json \
  --document-map local-reference/phase1-100/selected-document-ids.json
```

A 100-paper job uses the new snapshot bound to the approved decision and source
reviews:

```bash
research-ingest jobs start \
  --snapshot-id SNAPSHOT_ID \
  --chunking-configuration configs/phase1-e5-small-v2-chunking.example.json \
  --artifact-root data/artifacts \
  --membership-decision manifests/phase1-100-paper-membership-decision.json \
  --source-route-review local-reference/phase1-100/source-route-review.json \
  --source-content-review local-reference/phase1-100/source-content-review.json
```

Inspect the accepted snapshot and completed extraction job:

```bash
research-ingest snapshots inspect --snapshot-id 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c
research-ingest snapshots validate --snapshot-id 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c --minimum-papers 100
research-ingest jobs status --job-id 0e6bebc6-706d-49ec-9ad7-296ad48f1f89
```

If a new job is interrupted while pending or failed, resume its saved checkpoints.
Extraction and chunking have separate checkpoints. Retry a terminally failed paper
from the stage that failed (`extraction` or `chunking`), with a reason. A new job
with changed chunking settings can reuse the same persisted extraction when its
source and parser settings still match:

```bash
research-ingest jobs resume --job-id JOB_UUID --artifact-root data/artifacts
research-ingest jobs retry \
  --job-id JOB_UUID \
  --document-id DOCUMENT_UUID \
  --from-stage chunking \
  --reason "Reviewed cause and retry rationale" \
  --artifact-root data/artifacts
```

Use `--from-stage extraction` when the parser failed. The accepted 100-paper job
is already complete; its single expired lease was
recovered on the next attempt. Keep the job's recorded sources and configuration
fixed. Source or configuration changes require a new draft/job with new identities.

Then build or reconcile its local Qdrant collection and inspect IDs/counts without
printing passages:

```bash
research-ingest index rebuild \
  --snapshot-id SNAPSHOT_ID \
  --configuration configs/phase1-e5-small-v2-index.example.json
research-ingest index inspect \
  --snapshot-id SNAPSHOT_ID \
  --configuration configs/phase1-e5-small-v2-index.example.json
```

For a new pilot, keep each flagged table pending until its headers and selected
values have been checked against the source PDF. The 100-paper acceptance sample
reviewed 83 flagged tables and 20 ordinary-sample packet items; one item was a
figure, and all 102 table reviews are recorded in the [acceptance report](docs/reference/phase-1-100-paper-acceptance-report.md).

```bash
research-ingest snapshots review-table \
  --snapshot-id SNAPSHOT_ID \
  --extraction-id EXTRACTION_UUID \
  --table-ordinal TABLE_ORDINAL \
  --reviewer "Your name"
```

Keep a new snapshot in draft until its selected evidence has been reviewed and
its integrity validation passes. Public passage display remains disabled. For the
completed 100-paper run, 269/269 sampled unique numeric values were present, the
44,277 PostgreSQL and Qdrant evidence IDs reconciled, and all exact PDF artifacts
resolved. Snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` is finalized and passes
validation with 100 members, 44,277 expected chunks, and no issues.

Storage inspection and cleanup preview are also available. Cleanup candidates
include old database artifacts without document references, stale unregistered
content-addressed PDFs, and interrupted partial files. `storage cleanup` is preview
only by default. Add `--apply` to retire the listed files; it requires an explicit
age cutoff, refuses to run while an ingestion job is active, and protects every
artifact linked to a document. If interrupted, run it again to reconcile the
remaining unreferenced files. The 168-hour value below is an example, not a project
retention decision. Set `--root` and byte limits to match the active acquisition
configuration. The ten-paper source-artifact footprint set the 2 GiB cap. The 100-paper run
used 116,492,245 bytes. See the [acceptance report](docs/reference/phase-1-100-paper-acceptance-report.md)
for recovery, storage, and retry measurements; the disposable-file retention
period remains an explicit project decision.

```bash
research-ingest storage inspect --root data/artifacts
research-ingest storage cleanup-preview \
  --root data/artifacts --older-than-hours 168
research-ingest storage cleanup \
  --root data/artifacts --older-than-hours 168
research-ingest storage cleanup \
  --root data/artifacts --older-than-hours 168 --apply
```

Run database-backed commands only after applying the versioned migrations to
the intended database. The 100-paper decision selects 10 approved v1 references,
21 expansion candidates, 51 cited-work candidates and 18 discovery-cache candidates.
All 100 selected PDFs passed exact-source, checksum and persisted permission checks;
all 100 extractions completed. Six additional private follow-up PDFs remain
unassociated and do not count toward the accepted set. Any further full-text
acquisition needs its own reviewed membership and source permission evidence. The
accepted 100-paper snapshot is finalized; its evidence and verification are
recorded in the [acceptance report](docs/reference/phase-1-100-paper-acceptance-report.md).

Reproduce the parser comparison and its source-scored reference measurements using
the optional local environment described in the [extraction comparison report](docs/reference/phase-1-extraction-comparison.md). The [embedding feasibility report](docs/reference/phase-1-embedding-pilot.md) records its pinned model and reproduction settings. These model benchmarks are separate from ordinary CI.

## Environment files

- `environment.yaml` is the human-maintained Conda environment definition.
- `environment-linux-64.lock` records exact package builds for Linux x86-64.
- `pyproject.toml` defines the Python package and configures build, linting,
  type checking, and testing tools.

The YAML specification is the normal starting point for a new development
environment. The Linux x86-64 lock is consumed by GitHub Actions and the Docker
image, so the tested CI environment and container runtime use the same exact
Conda packages. The image installs the local project with dependency resolution
disabled; its runtime dependencies come from that lock. Regenerate the lock
after deliberate environment changes.

## Phase 1 learning plan

The [detailed ingestion plan](docs/plans/phase-1-corpus-ingestion.md) contains
14 approved tasks, dependencies, learning objectives and acceptance criteria.
A continuing agent should read the [Phase 1 handoff](docs/plans/phase-1-learning-handoff.md)
for current progress and the next exercise. The user implements the tasks unless
coding is explicitly delegated.
