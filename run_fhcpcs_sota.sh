#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The Python runner provides a strict external timeout, manifest, raw logs,
# verified tours, and one JSONL record per instance. Extra arguments are
# forwarded, e.g. --timeout 60 --instances 339,479,797.
exec python3 "$REPO_DIR/tools/hcp_benchmark.py" \
    --variants current_full \
    --set full \
    "$@"
