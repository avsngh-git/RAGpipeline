#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/demo_load.sh [--with-llm] [--reset] [--help]

Prepare the local CPU demo. --with-llm also starts Ollama and grants the demo key
research scope; it requires an NVIDIA GPU. --reset removes Compose volumes and
the bundle load marker before preparing the demo again.
EOF
}

with_llm=0
reset=0
for argument in "$@"; do
  case "$argument" in
    --with-llm) with_llm=1 ;;
    --reset) reset=1 ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$argument" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "$(dirname "$0")/.."

announce() {
  printf '==> %s\n' "$1"
}

announce 'Checking the demo bundle tools'
if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Missing required tool: docker (with the Compose plugin).' >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' 'Missing required tool: docker compose.' >&2
  exit 1
fi
for tool in curl sha256sum tar; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Missing required tool: %s.\n' "$tool" >&2
    exit 1
  fi
done

DEMO_BUNDLE_VERSION="${DEMO_BUNDLE_VERSION:-v1}"
DEMO_BUNDLE_URL="${DEMO_BUNDLE_URL:-https://github.com/avsngh-git/RAGpipeline/releases/download/demo-data-${DEMO_BUNDLE_VERSION}/research-demo-${DEMO_BUNDLE_VERSION}.tar}"
archive="research-demo-${DEMO_BUNDLE_VERSION}.tar"
archive_dir="research-demo-${DEMO_BUNDLE_VERSION}"
loaded_marker="demo-data/.loaded-${DEMO_BUNDLE_VERSION}"

if (( reset )); then
  announce 'Resetting Compose volumes and demo load marker'
  docker compose down -v
  mkdir -p demo-data
  rm -f demo-data/.loaded-*
  rm -f demo-data/api-key
fi

announce "Downloading and verifying ${archive}"
mkdir -p demo-data
if [[ ! -f "demo-data/${archive}" ]]; then
  curl --fail --location --silent --show-error \
    "$DEMO_BUNDLE_URL" -o "demo-data/${archive}"
fi
if [[ ! -f "demo-data/${archive}.sha256" ]]; then
  curl --fail --location --silent --show-error \
    "${DEMO_BUNDLE_URL}.sha256" -o "demo-data/${archive}.sha256"
fi
(cd demo-data && sha256sum -c "${archive}.sha256")
tar -xf "demo-data/${archive}" -C demo-data

announce 'Pulling the API image or building it locally'
docker compose pull api || docker compose build api

announce 'Starting PostgreSQL and Qdrant'
docker compose up -d --wait postgres qdrant

announce 'Applying database migrations'
docker compose run --rm --no-deps api research-migrate

if [[ ! -f "$loaded_marker" ]]; then
  announce 'Loading the demo bundle'
  docker compose run --rm --no-deps api research-demo load \
    --bundle "/demo-data/${archive_dir}"
  touch "$loaded_marker"
fi

announce 'Downloading the pinned embedding and reranker models'
docker compose run --rm --no-deps \
  -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
  api research-demo fetch-models

if [[ ! -f demo-data/api-key ]]; then
  announce 'Creating the local demo API key'
  key_args=(--principal demo --scope read)
  if (( with_llm )); then
    key_args+=(--scope research)
  fi
  key_json="$(docker compose run --rm --no-deps api research-keys create "${key_args[@]}")"
  api_key="$(printf '%s' "$key_json" | docker compose run --rm --no-deps -T api python -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')"
  (umask 077 && printf '%s\n' "$api_key" > demo-data/api-key)
  unset api_key key_json
fi

if (( with_llm )); then
  announce 'Starting the optional Ollama profile'
  docker compose --profile llm up -d ollama
  cat <<'EOF'
Import the local model once with:
  scripts/phase3_fetch_generator.sh 2b
  docker compose --profile llm exec -T ollama ollama create qwen3.5-2b-text:q4_k_m \
    -f /dev/stdin < configs/ollama/qwen3.5-2b-text.Modelfile
EOF
fi

announce 'Starting the API and waiting for model readiness'
docker compose up -d --wait api

printf '%s\n' 'UI: http://127.0.0.1:8000/'
printf '%s\n' 'API key: demo-data/api-key'
docker compose run --rm --no-deps -T api python -c '
import json
from pathlib import Path

manifest = json.loads(Path("/demo-data/'"$archive_dir"'/manifest.json").read_text(encoding="utf-8"))
for run in manifest["runs"]:
    print(f"http://127.0.0.1:8000/#run={run[\"run_id\"]}  ({run[\"mode\"]})")
'
