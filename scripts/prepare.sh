#!/usr/bin/env bash
set -euo pipefail

head_actual=$(git -C "${SOURCE_ROOT}" rev-parse --verify HEAD)
base_actual=$(git -C "${BASE_ROOT}" rev-parse --verify HEAD)
if [[ "${head_actual}" != "${HEAD_SHA}" || "${base_actual}" != "${BASE_SHA}" ]]; then
  printf '%s\n' 'Ordo: checkouts do not match the immutable pull request head/base SHA.' >&2
  exit 1
fi

# The only fetch here uses a local directory. No remote credentials or refetch.
git -C "${SOURCE_ROOT}" fetch --no-tags "${BASE_ROOT}" \
  "+${BASE_SHA}:refs/remotes/ordo/base"
imported_base=$(git -C "${SOURCE_ROOT}" rev-parse --verify refs/remotes/ordo/base)
if [[ "${imported_base}" != "${BASE_SHA}" ]]; then
  printf '%s\n' 'Ordo: imported base history does not match the event SHA.' >&2
  exit 1
fi
if ! git -C "${SOURCE_ROOT}" merge-base HEAD refs/remotes/ordo/base; then
  printf '%s\n' 'Ordo: head and base histories have no merge base; cannot analyze this pull request.' >&2
  exit 1
fi

python3 "${ACTION_PATH}/scripts/validate_path.py"
