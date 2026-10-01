#!/usr/bin/env bash
set -euo pipefail

readonly model_name="Qwen3.5-4B-Q4_K_M.gguf"
readonly model_revision="35edb278feb3f797d270a605d9745cab09538c12"
readonly model_sha256="00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4"
readonly model_url="https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/${model_revision}/${model_name}"

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
