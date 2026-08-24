#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$REPO_DIR/tools/hcp_benchmark.py" \
    --variants paper_upstream,current_base,current_full \
    --set smoke \
    --timeout 120 \
    "$@"
