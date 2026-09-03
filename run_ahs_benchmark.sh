#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${AHS_PYTHON:-python3}"
if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
fi

"$PYTHON_BIN" "$REPO_DIR/tools/ahs_solver.py" --policy residual_v1 --build-only

exec "$PYTHON_BIN" "$REPO_DIR/tools/hcp_benchmark.py" \
    --config "$REPO_DIR/benchmarks/ahs_variants.json" \
    --set historical_open_33 \
    --variants ahs_residual_v1 \
    "$@"
