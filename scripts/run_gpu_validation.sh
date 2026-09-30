#!/usr/bin/env bash
# Run only when the task owner launches this on the declared H100 machine.
# This script never calls cloud provisioning APIs and never creates a GPU pod.
set -euo pipefail
if [[ $# -ne 2 ]]; then
  printf 'Usage: %s LOCAL_MODEL_DIRECTORY NEW_EVIDENCE_DIRECTORY\n' "$0" >&2
  exit 2
fi
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
python_bin="${JEV_PYTHON:-$repo_dir/.venv/bin/python}"
model_dir="$("$python_bin" -c 'import os,sys;print(os.path.abspath(sys.argv[1]))' "$1")"
evidence_dir="$2"
test ! -e "$evidence_dir"
mkdir -p "$evidence_dir"
evidence_dir="$(cd "$evidence_dir" && pwd)"
cd "$repo_dir"
# Model acquisition is a separate, network-enabled setup step.
if [[ ! -f "$model_dir/jevbench_model_pin.json" ]]; then
  "$python_bin" -m jevbench download-model --destination "$model_dir"
fi
model_dir="$(cd "$model_dir" && pwd)"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false
"$python_bin" -m pip freeze > "$evidence_dir/resolved-requirements.txt"
nvidia-smi -q > "$evidence_dir/nvidia-smi.txt"
"$python_bin" -m jevbench materialize-baseline --output "$evidence_dir/baseline-prompts.json"
"$python_bin" -m jevbench gpu-smoke --model "$model_dir" --prompts "$evidence_dir/baseline-prompts.json" --data "$repo_dir/data" --output "$evidence_dir/gpu-smoke.json"
"$python_bin" -m jevbench baseline --model "$model_dir" --prompts "$evidence_dir/baseline-prompts.json" --data "$repo_dir/data" --output "$evidence_dir/b0-validation.json"
"$python_bin" -m jevbench work --model "$model_dir" --prompts "$evidence_dir/baseline-prompts.json" --data "$repo_dir/data" --output "$evidence_dir/b1-work"
"$python_bin" "$script_dir/export_candidate.py" --work-artifact "$evidence_dir/b1-work/candidate.json" --output "$evidence_dir/b1-candidate.json"
printf 'Real public B0/B1 evidence saved. Hidden Judge and official Harness trajectory remain separate task-owner steps.\n'
