#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${STATE_DIR:-}" ]]; then
  if [[ -f "${STATE_DIR}/summary-published" || -f "${STATE_DIR}/failure-published" ]]; then
    exit 0
  fi
fi
{
  printf '# Ordo — Review Path\n\n'
  printf 'Ordo could not analyze this pull request.\n\n'
  printf 'See the workflow logs for details.\n'
} >> "${GITHUB_STEP_SUMMARY}"
if [[ -n "${STATE_DIR:-}" && -d "${STATE_DIR}" ]]; then
  touch -- "${STATE_DIR}/failure-published"
fi
