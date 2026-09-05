#!/usr/bin/env bash
set -euo pipefail

REPORT_PATH=$(mktemp "${STATE_DIR}/report.XXXXXXXX")
cd -- "${MODULE_ROOT}"
"${ORDO_BIN}" \
  --diff \
  --diff-base refs/remotes/ordo/base \
  --format json \
  "./..." \
  > "${REPORT_PATH}"

if [[ ! -f "${REPORT_PATH}" || ! -s "${REPORT_PATH}" || -L "${REPORT_PATH}" ]]; then
  printf '%s\n' 'Ordo: analysis did not produce a non-empty regular JSON report.' >&2
  exit 1
fi
printf 'report_path=%s\n' "${REPORT_PATH}" >> "${GITHUB_OUTPUT}"
