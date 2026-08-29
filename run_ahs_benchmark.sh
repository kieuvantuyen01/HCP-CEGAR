#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$REPO_DIR/tools/ahs_solver.py" --policy rule_v1 --build-only

exec python3 "$REPO_DIR/tools/hcp_benchmark.py" \
    --config "$REPO_DIR/benchmarks/ahs_variants.json" \
    --set historical_open_33 \
    "$@"
