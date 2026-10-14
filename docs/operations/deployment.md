# Deployment and operations

This guide covers the released API image and the local Compose environment. The Compose
stack binds its published ports to loopback. The small mode uses PostgreSQL, Qdrant and
the API on CPU; Ollama is an optional profile for live research runs. See the
[Compose configuration](../../docker-compose.yml) and
[Phase 6 delivery decision](../adr/0033-phase6-delivery-without-hosting.md).

## Release flow

The [CI workflow](../../.github/workflows/ci.yml) runs checks, applies migrations in its
PostgreSQL service, builds and scans the image, then pushes
`ghcr.io/avsngh-git/ragpipeline:sha-<12-character-commit>` only after a successful push
to `main`. Before making a version tag, check that CI passed for the exact `main` commit
you intend to release. The
[release workflow](../../.github/workflows/release.yml) looks up that commit's SHA image,
promotes the same digest to the version tag and `latest`, and creates a GitHub Release
whose notes include the digest. It does not rebuild the image.

Phase 6 release tags use the `v0.6.x` series. For example, after confirming the main CI
run for the chosen commit is green, set `MAIN_COMMIT` to that commit SHA, then create and
push its version tag:

```bash
git tag v0.6.0 "$MAIN_COMMIT"
git push origin v0.6.0
```

The first GHCR push creates a private package. Set the package visibility to public once
in [the container package settings](https://github.com/users/avsngh-git/packages/container/ragpipeline/settings).
The image and release policy is recorded in
[ADR-0033](../adr/0033-phase6-delivery-without-hosting.md).

## Run a pinned version

Choose a released version and set the image before starting Compose:

```bash
export RESEARCH_PLATFORM_IMAGE=ghcr.io/avsngh-git/ragpipeline:v0.6.0
docker compose up -d
```

For repeatable deployments, pin the image digest shown in the GitHub Release notes:
replace `<image-digest>` with the digest from that release before running the command.

```bash
export RESEARCH_PLATFORM_IMAGE="ghcr.io/avsngh-git/ragpipeline@sha256:<image-digest>"
docker compose up -d
```

The image is built for `linux/amd64`; the Compose service selects that platform.
The image contains the application and migrations, while model weights are fetched into
the `model_cache` volume by [`research-demo fetch-models`](../../src/research_platform/demo/cli.py).
See the [Dockerfile](../../Dockerfile) and
[Compose configuration](../../docker-compose.yml).

## Configuration

The `api` service sets these variables in Compose. The API key is supplied separately in
an HTTP authorization header; do not put keys or other secrets in the Compose YAML.
Compose reads values used for interpolation from the environment or a local `.env` file.
The repository ignores `.env`; keep real credentials there and out of commits. See the
[Compose configuration](../../docker-compose.yml),
[settings](../../src/research_platform/config.py), and
[authentication guide](authentication.md).

| Variable | Compose value or default | Purpose |
| --- | --- | --- |
| `RESEARCH_PLATFORM_ENVIRONMENT` | `development` | Selects the runtime environment. |
| `RESEARCH_PLATFORM_LOG_LEVEL` | `INFO` | Sets API log verbosity. |
| `RESEARCH_PLATFORM_DATABASE_URL` | Built from `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` for the `postgres` service. | Connects the API to PostgreSQL. |
| `RESEARCH_PLATFORM_QDRANT_URL` | `http://qdrant:6333` | Connects the API to Qdrant. |
| `RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE` | `trusted_private_local` | Enables the local UI to display evidence text from the demo bundle. |
| `RESEARCH_PLATFORM_MODEL_DEVICE` | `cpu` | Selects CPU inference for the reviewer mode. |
| `HF_HOME` | `/models/hf` | Stores downloaded embedding model files in the `model_cache` volume. |
| `RESEARCH_PLATFORM_RERANKER_CACHE_DIR` | `/models/reranker` | Stores downloaded reranker files in the `model_cache` volume. |
| `HF_HUB_OFFLINE` | `1` | Uses cached Hugging Face files after the setup script fetches models. |
| `TRANSFORMERS_OFFLINE` | Same value as `HF_HUB_OFFLINE` | Keeps Transformers in offline mode after setup. |
| `RESEARCH_PLATFORM_LLM_BASE_URL` | `http://ollama:11434` | Sets the optional Ollama endpoint. |
| `RESEARCH_PLATFORM_LLM_MODEL` | `qwen3.5-2b-text:q4_k_m` | Selects the optional Ollama model. |
| `OPENALEX_API_KEY` | Empty | Optional OpenAlex credential for online discovery. |
| `RESEARCH_PLATFORM_DEPENDENCY_TIMEOUT_SECONDS` | `2` | Bounds PostgreSQL and Qdrant readiness checks. |

For the local demonstration, run [`scripts/demo_load.sh`](../../scripts/demo_load.sh)
before `docker compose up -d`. It downloads and verifies the demo bundle, applies
migrations, loads the data and fetches the model files.

## Migrations

Apply migrations explicitly before starting a new image version. The runner applies
pending SQL files in order and records each applied version. It has no down-migration
command, so treat schema migrations as forward-only and take a PostgreSQL backup first.
The image sets `RESEARCH_PLATFORM_MIGRATIONS_DIR` to `/app/migrations`; keep that path
unless you intentionally provide a different migration directory. See the
[Dockerfile](../../Dockerfile).
See [`migrations.py`](../../src/research_platform/persistence/migrations.py),
[ADR-0033](../adr/0033-phase6-delivery-without-hosting.md), and the
[Compose setup script](../../scripts/demo_load.sh).

```bash
export RESEARCH_PLATFORM_IMAGE=ghcr.io/avsngh-git/ragpipeline:v0.6.0
docker compose pull api
docker compose run --rm --no-deps api research-migrate
docker compose up -d
```

## Backup and restore

### PostgreSQL

The PostgreSQL container supplies `pg_dump` and `pg_restore`. Set `BACKUP_FILE` to a
protected location outside the repository. The custom-format archive contains the
database name and can be restored as a replacement database.

```bash
export BACKUP_FILE=/secure/location/research.dump
umask 077
docker compose exec -T postgres sh -c \
  'pg_dump --format=custom --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  > "$BACKUP_FILE"
```

To restore that archive, stop the API first. `--create` recreates the database recorded
in the archive; this replaces the current database contents.

```bash
docker compose stop api
docker compose exec -T postgres sh -c \
  'pg_restore --clean --create --if-exists --no-owner --no-privileges --username="$POSTGRES_USER" --dbname=postgres' \
  < "$BACKUP_FILE"
docker compose up -d
```

The Compose service defines the PostgreSQL image, credentials and persistent volume in
[`docker-compose.yml`](../../docker-compose.yml). Keep the dump protected because it
contains the application database.

### Qdrant

Qdrant is a derived search index. You can save a snapshot through its REST API, or
rebuild the published generation from PostgreSQL. The serving configuration names the
passage and paper collections; repeat the snapshot commands for each collection. The
snapshot endpoints below match the implementation used by
[`research-demo`](../../src/research_platform/demo/qdrant.py).

```bash
export QDRANT_URL=http://127.0.0.1:6333
export COLLECTION=research-passages-gte-bm25-v1
export SNAPSHOT_NAME="<name-from-qdrant-response>"
export SNAPSHOT_FILE=/secure/location/research-passages.snapshot

curl --fail --request POST \
  "$QDRANT_URL/collections/$COLLECTION/snapshots?wait=true"
curl --fail --output "$SNAPSHOT_FILE" \
  "$QDRANT_URL/collections/$COLLECTION/snapshots/$SNAPSHOT_NAME"
```

The demo restore helper refuses to restore over an existing collection. Restore into an
empty target collection; see the
[`research-demo` restore check](../../src/research_platform/demo/qdrant.py).

```bash
curl --fail --request POST \
  --form "snapshot=@$SNAPSHOT_FILE" \
  "$QDRANT_URL/collections/$COLLECTION/snapshots/upload?priority=snapshot&wait=true"
```

To rebuild the generation from PostgreSQL, use empty Qdrant collections and the same
generation configuration used by the running service:

```bash
docker compose run --rm --no-deps api research-ingest generations rebuild \
  --collection-name research-corpus \
  --configuration configs/phase35-generation-index-lexical.example.json
```

The rebuild command replays published generations from PostgreSQL into empty Qdrant
collections. Follow the [index-generation operations](phase-2-search.md#index-generations-phase-35)
and [ADR-0023](../adr/0023-phase35-index-generations.md); do not point a rebuild at a
non-empty collection. The demo setup fetches the pinned embedding and reranker model
files again with `research-demo fetch-models`.

## Rollback

Set `RESEARCH_PLATFORM_IMAGE` to the previous release tag and run `docker compose up -d`.
If the new version already applied migrations, stop the API and restore the PostgreSQL
backup taken before the upgrade before bringing the previous image up. Restore the
matching Qdrant snapshots or rebuild the derived index if needed. The release workflow
promotes images and creates releases; the repository has no automatic deployment step.
See [ADR-0033](../adr/0033-phase6-delivery-without-hosting.md), the
[release workflow](../../.github/workflows/release.yml), and the
[rollback requirements](../agents/scientific-research-platform-source-of-truth.md).

## Failure recovery

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `/ready` returns `503` | Its response identifies unavailable PostgreSQL, Qdrant, search runtime, or research runtime dependencies. | Check `docker compose ps` and `docker compose logs api`; start or repair the named dependency, then recheck `/ready`. The readiness check reports dependency status without connection details. |
| Search reports missing model files while offline | The model cache is empty or incomplete. | Fetch the pinned models while online, then restart the API: `docker compose run --rm --no-deps -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 api research-demo fetch-models`. The files live in the `model_cache` volume. |
| Qdrant collection is missing | Its volume or collection was removed, or the demo bundle was not loaded. | If PostgreSQL still has the published generation, rebuild into empty collections with the command in [Backup and restore](#qdrant). For a fresh demo database, rerun `scripts/demo_load.sh` to load its Qdrant snapshots. |
| A research run was interrupted | The API stopped while a run was queued or running. | On startup, the executor resumes a running run from its last checkpoint. It retries a run at most `2` times, then records `resume_exhausted`; start a new run if it has exhausted retries. See [ADR-0019](../adr/0019-phase3-research-run-execution.md). |
| Ollama is unreachable | The optional `llm` profile is stopped, or its model has not been imported. | Start it with `docker compose --profile llm up -d ollama`, then follow the one-time import command in the [generator operations guide](phase-3-generator.md). This path requires an NVIDIA GPU. |
| Docker reports no space left | Docker images, model caches or named data volumes use the available disk. | Inspect usage with `docker system df`; remove unused images with `docker image prune`. Do not remove named volumes unless you intend to erase PostgreSQL, Qdrant, model-cache or Ollama data. |
| An API request returns `429` | The principal exceeded a route-class limit or the active-run limit. | Wait for the `Retry-After` interval and retry. The [authentication guide](authentication.md#errors) lists the defaults and response behavior. |

The `/ready` endpoint checks PostgreSQL and Qdrant and also reports whether the search
and research runtimes initialized. See the [readiness route](../../src/research_platform/api/app.py)
and [dependency checks](../../src/research_platform/services/readiness.py).

## API keys

Create a key with only the scopes the operator needs. `create` prints the key once, so
protect the terminal output and store it securely. `list` shows key prefixes and scopes;
`revoke` takes the key ID. Set `KEY_ID` to the ID shown by `list`. The commands below
run inside the Compose API image:

```bash
docker compose exec api research-keys create \
  --principal operator --scope read --scope research
docker compose exec api research-keys list
docker compose exec api research-keys revoke "$KEY_ID"
```

See the [authentication guide](authentication.md) for scope meanings and key lifecycle.

## Observability

View API logs with `docker compose logs --follow api`. The API exposes Prometheus
metrics at `http://127.0.0.1:8000/metrics`. Traces are written as JSONL in the API
container's configured trace directory by default; Compose does not mount that directory
as persistent storage. In the `development` environment, trace content
defaults to `full`, which can include prompts, outputs and passage text. Keep trace files
private and configure an OTLP endpoint only when you have a protected trace backend.
See the [observability guide](observability.md),
[trace settings](../../src/research_platform/observability/tracing.py),
[trace content policy](../../src/research_platform/observability/content.py), and
[metrics endpoint](../../src/research_platform/api/app.py).

## Reset the demo

To load the demo bundle again from a clean Compose state, run:

```bash
scripts/demo_load.sh --reset
docker compose up -d
```

The reset option runs `docker compose down -v`, removes the demo load markers and local
API key, then repeats the setup. This deletes Compose named volumes used by the stack,
including PostgreSQL, Qdrant and model-cache data. Back up anything you need before
resetting. See [`demo_load.sh`](../../scripts/demo_load.sh).
