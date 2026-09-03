#!/usr/bin/env bash
set -euo pipefail

# General AHS benchmark wrapper using the repository's AHS config. The rule_v2
# build covers every backend used by its single-backend and residual variants.
# Callers choose the instance set, variant, timeout, and output through "$@".

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${AHS_PYTHON:-python3}"
if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
fi

for argument in "$@"; do
    case "$argument" in
        --config|--config=*)
            echo "run_ahs_benchmark.sh fixes the AHS config; call tools/hcp_benchmark.py directly for another config." >&2
            exit 2
            ;;
    esac
done

"$PYTHON_BIN" "$REPO_DIR/tools/ahs_solver.py" --policy rule_v2 --build-only

exec "$PYTHON_BIN" "$REPO_DIR/tools/hcp_benchmark.py" \
    --config "$REPO_DIR/benchmarks/ahs_variants.json" \
    "$@"
