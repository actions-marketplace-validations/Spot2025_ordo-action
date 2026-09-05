#!/usr/bin/env bash
set -euo pipefail

# Give every invocation its own state, including when context validation fails.
state_dir=$(mktemp -d "${RUNNER_TEMP}/ordo-action.XXXXXXXX")
printf 'state_dir=%s\n' "${state_dir}" >> "${GITHUB_OUTPUT}"

if [[ "${EVENT_NAME:-}" != pull_request ]]; then
  printf '%s\n' 'Ordo requires the pull_request event; pull_request_target and all other events are unsupported.' >&2
  exit 1
fi

python3 - <<'PY'
import os
import re
import sys
from urllib.parse import urlsplit

def require(name, pattern):
    if not re.fullmatch(pattern, os.environ.get(name, "")):
        sys.exit(f"Ordo: missing or invalid pull_request context: {name}")

for name in ("BASE_REPOSITORY", "HEAD_REPOSITORY"):
    require(name, r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
for name in ("BASE_SHA", "HEAD_SHA"):
    require(name, r"[0-9a-fA-F]{40}")
require("PR_NUMBER", r"[1-9][0-9]*")
server = os.environ.get("SERVER_URL", "")
if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?/?", server):
    sys.exit("Ordo: missing or invalid pull_request context: SERVER_URL")
if not urlsplit(server).hostname:
    sys.exit("Ordo: missing or invalid pull_request context: SERVER_URL")
PY
