# 6. Command-line tools

Installing the package adds eight commands. They all read `RESEARCH_PLATFORM_DATABASE_URL` (and `RESEARCH_PLATFORM_QDRANT_URL` where they touch the index); see [Configuration](07-configuration.md). Inside the Compose stack, run them through the API image, for example `docker compose run --rm --no-deps api research-keys list`.

Every command supports `--help`, except `research-migrate` and `research-worker`, which take no arguments and start immediately.

| Command | Purpose |
| --- | --- |
| [`research-migrate`](#research-migrate) | Apply database migrations |
| [`research-keys`](#research-keys) | Manage API keys |
| [`research-demo`](#research-demo) | Export, load and prepare the demo bundle |
| [`research-ingest`](#research-ingest) | Build and maintain the corpus and search index |
| [`research-worker`](#research-worker) | Process queued ingestion requests |
| [`research-runs`](#research-runs) | Inspect, explain, reproduce and prune research runs |
| [`research-eval`](#research-eval) | Run and compare evaluation suites |
| [`research-maintenance`](#research-maintenance) | Apply data retention |

## research-migrate

Applies pending SQL files from `migrations/` in order, records each in `schema_migrations`, and holds an advisory lock so two runners cannot race. It is safe to run again. Migrations are forward-only; there is no down command. In the image, `RESEARCH_PLATFORM_MIGRATIONS_DIR=/app/migrations`. `python scripts/migrate.py` does the same from a checkout.

## research-keys

```bash
research-keys create --principal alice --scope read --scope research   # prints the key once, as JSON
research-keys list                                                     # prefixes and scopes, never keys
research-keys revoke KEY_ID
```

Scopes are `read`, `research`, `ingest` and `admin`. Principal names use lower-case letters, digits, `.`, `_` and `-`, up to 63 characters.

## research-demo

```bash
research-demo load --bundle /demo-data/research-demo-v1        # load PostgreSQL rows and Qdrant snapshots
research-demo fetch-models                                     # download pinned embedding and reranker revisions
research-demo export --snapshot-id ID --run-principal NAME --output DIR [--bundle-version v1]
```

`load` refuses to restore over existing Qdrant collections. `export` writes only allowlisted tables and display-cleared passages, plus a manifest and `ATTRIBUTION.md`. It is the owner's release step ([ADR-0032](../adr/0032-phase6-public-cc-by-demo-collection.md)).

## research-ingest

The corpus toolkit. [Corpus and ingestion](08-corpus-and-ingestion.md) explains the workflow; this is the command map.

| Group | Subcommands | Purpose |
| --- | --- | --- |
| `discover` | (options: `--config`, `--resume`) | Run a bounded, resumable OpenAlex discovery from a JSON configuration |
| `manifest` | `prepare`, `export`, `import`, `approve`, `report` | Build a shortlist, export it for review, import decisions, approve it, report yield and coverage |
| `membership` | `import`, `acquire` | Refresh metadata for selected papers; download their PDFs within caps |
| `citations` | `enrich` | Fetch bounded metadata for unresolved cited works |
| `jobs` | `start`, `resume`, `retry`, `status` | Run extraction and chunking for a draft snapshot, with checkpoints and targeted retries |
| `snapshots` | `create`, `add`, `add-membership`, `remove`, `inspect`, `evidence`, `review-table`, `apply-corrections`, `validate`, `finalize` | Assemble, review, validate and freeze snapshots |
| `index` | `rebuild`, `inspect`, `query`, `lexical-build`, `lexical-query` | Snapshot-scoped Qdrant collections and BM25S indexes (Phase 1–2 tooling) |
| `generations` | `build`, `sync-papers`, `verify`, `publish`, `rebuild`, `purge`, `lexical-settings` | Index generations: the serving path since Phase 3.5 |
| `storage` | `inspect`, `cleanup-preview`, `cleanup` | Artifact storage limits and safe cleanup (`cleanup` previews unless `--apply`) |

## research-worker

Claims queued ingestion requests from the PostgreSQL outbox, one at a time, and publishes the next generation. It is configured by environment:

| Variable | Default | Meaning |
| --- | --- | --- |
| `RESEARCH_PLATFORM_INGESTION_HANDLER` | `noop` | `online` to really acquire, extract and publish |
| `RESEARCH_PLATFORM_ARTIFACT_ROOT` | `data/artifacts` | Where PDFs are stored |
| `RESEARCH_PLATFORM_WORKER_POLL_SECONDS` | `5` | Queue poll interval |
| `RESEARCH_PLATFORM_WORKER_METRICS_PORT` | `9101` | Prometheus port on 127.0.0.1; `0` disables it |

`SIGINT` or `SIGTERM` stops it cleanly. A crashed worker's request is reclaimed when its lease expires. The worker needs the `pdf` extra (Docling) and runs in the host Conda environment; the released image does not include Docling.

## research-runs

```bash
research-runs show RUN_ID                     # the stored run view
research-runs explain RUN_ID [--json] [--spans local-reference/traces/research-api.jsonl]
research-runs reproduce RUN_ID [--json]       # exits 0 only if the configuration rebuilds identically
research-runs prune --older-than-days 30      # permanently deletes terminal runs and their checkpoints
```

See [Evaluation: diagnosing a run](11-evaluation.md#diagnosing-a-run).

## research-eval

```bash
research-eval run SUITE [--option KEY=VALUE ...] [--notes TEXT]
research-eval list [--suite SUITE] [--limit N]
research-eval show EXPERIMENT_ID
research-eval compare BASELINE_ID CANDIDATE_ID [--with-stages] [--output local-reference/...]
```

Suites are `scripted-regression`, `retrieval-dev`, `agent-dev` and `security-live`. See [Evaluation](11-evaluation.md).

## research-maintenance

```bash
research-maintenance retention                                   # report what is eligible
research-maintenance retention --apply                           # delete it
research-maintenance retention --apply --collection-name NAME --configuration FILE   # also purge retired Qdrant points
```

It deletes LangGraph checkpoints 7 days after a completed run and 30 days after a failed one, and model-call text after 90 days. Run rows, tool calls, claims and drafts are kept. Nothing runs automatically. See the [retention guide](../operations/retention.md).

Next: [Configuration](07-configuration.md).
