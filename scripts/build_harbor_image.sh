#!/usr/bin/env bash
# Build/download only. Does not allocate a GPU or run model inference.
set -euo pipefail
if [[ $# -ne 2 ]]; then
  printf 'Usage: %s STAGED_TASK_DIRECTORY LOCAL_IMAGE_TAG\n' "$0" >&2
  exit 2
fi
task_dir="$(cd "$1" && pwd)"
image_tag="$2"
test -f "$task_dir/environment/Dockerfile"
test -f "$task_dir/tests/input_manifest.json"
docker build --tag "$image_tag" "$task_dir/environment"
container_id="$(docker create "$image_tag")"
trap 'docker rm -f "$container_id" >/dev/null' EXIT
docker cp "$container_id:/opt/jev-build/runtime_manifest.json" "$task_dir/tests/runtime_manifest.json"
docker cp "$container_id:/opt/jev-build/resolved-requirements.txt" "$task_dir/tests/resolved-requirements.txt"
docker image inspect --format '{{.Id}}' "$image_tag" > "$task_dir/tests/built-image-id.txt"
# Both this lock and the image ID are frozen BEFORE exposing Work to an agent.
printf 'Image built and immutable runtime lock extracted. GPU smoke and official Harbor validation are still required.\n'
