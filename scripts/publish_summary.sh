#!/usr/bin/env bash
set -euo pipefail

summary_path=$(mktemp "${STATE_DIR}/summary.XXXXXXXX")
python3 "${ACTION_PATH}/scripts/render_summary.py" \
  "${REPORT_PATH}" \
  --server-url "${SERVER_URL}" \
  --base-repository "${BASE_REPOSITORY}" \
  --head-repository "${HEAD_REPOSITORY}" \
  --pull-request "${PR_NUMBER}" \
  --sha "${HEAD_SHA}" \
  "--source-prefix=${SOURCE_PREFIX}" \
  > "${summary_path}"

cat -- "${summary_path}" >> "${GITHUB_STEP_SUMMARY}"
touch -- "${STATE_DIR}/summary-published"
