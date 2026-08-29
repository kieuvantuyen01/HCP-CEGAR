#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$REPO_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Missing $PYTHON_BIN. Run ./setup_dependencies.sh first." >&2
    exit 1
fi
if ! "$PYTHON_BIN" -c 'from pysat.solvers import Cadical195' >/dev/null 2>&1; then
    echo "PySAT/CaDiCaL is unavailable. Run ./setup_dependencies.sh again." >&2
    exit 1
fi
if [[ ! -f "$REPO_DIR/external/SAT_HCP/ChineseRemainderConvert/encode.py" ]]; then
    echo "Missing the pinned CRE source. Run ./setup_dependencies.sh first." >&2
    exit 1
fi

export PATH="$REPO_DIR/.venv/bin:$PATH"
exec "$PYTHON_BIN" "$REPO_DIR/tools/hcp_benchmark.py" \
    --config "$REPO_DIR/benchmarks/hybrid_variants.json" \
    --variants cre_cegar_m420 \
    "$@"
