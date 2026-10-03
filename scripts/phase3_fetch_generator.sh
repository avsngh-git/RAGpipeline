#!/usr/bin/env bash
set -euo pipefail

# Usage: scripts/phase3_fetch_generator.sh [2b|4b]   (default: 2b, the active model)
case "${1:-2b}" in
  2b)
    readonly model_repo="unsloth/Qwen3.5-2B-GGUF"
    readonly model_name="Qwen3.5-2B-Q4_K_M.gguf"
    readonly model_revision="f6d5376be1edb4d416d56da11e5397a961aca8ae"
    readonly model_sha256="aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223"
    ;;
  4b)
    readonly model_repo="unsloth/Qwen3.5-4B-GGUF"
    readonly model_name="Qwen3.5-4B-Q4_K_M.gguf"
    readonly model_revision="35edb278feb3f797d270a605d9745cab09538c12"
    readonly model_sha256="00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4"
    ;;
  *)
    printf 'Usage: %s [2b|4b]\n' "$0" >&2
    exit 2
    ;;
esac
readonly model_url="https://huggingface.co/${model_repo}/resolve/${model_revision}/${model_name}"

readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly project_root="$(cd -- "${script_dir}/.." && pwd)"
readonly model_dir="${project_root}/local-reference/phase3-models"
readonly model_path="${model_dir}/${model_name}"

verify_model() {
  printf '%s  %s\n' "${model_sha256}" "${model_path}" | sha256sum --check --status
}

mkdir -p "${model_dir}"

if [[ -f "${model_path}" ]] && verify_model; then
  printf 'Verified existing model: %s\n' "${model_path}"
  exit 0
fi

readonly temporary_path="$(mktemp "${model_dir}/.${model_name}.XXXXXX")"
trap 'rm -f -- "${temporary_path}"' EXIT

curl -fL --retry 3 --output "${temporary_path}" "${model_url}"
printf '%s  %s\n' "${model_sha256}" "${temporary_path}" | sha256sum --check
mv -- "${temporary_path}" "${model_path}"
trap - EXIT
printf 'Downloaded and verified model: %s\n' "${model_path}"
