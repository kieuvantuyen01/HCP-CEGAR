#!/usr/bin/env bash
set -euo pipefail

# Fixed experiment wrapper: residual_v1 on the historical 33-instance core.
# Set/config/variant overrides are rejected so build and execution cannot diverge.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${AHS_PYTHON:-python3}"
if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
fi

for argument in "$@"; do
    case "$argument" in
        --config|--config=*|--instance-sets|--instance-sets=*|--set|--set=*|--instances|--instances=*|--variants|--variants=*)
            echo "run_ahs_residual33.sh fixes config, set, and variant; use run_ahs_benchmark.sh for overrides." >&2
            exit 2
            ;;
    esac
done

"$PYTHON_BIN" "$REPO_DIR/tools/ahs_solver.py" --policy residual_v1 --build-only

exec "$PYTHON_BIN" "$REPO_DIR/tools/hcp_benchmark.py" \
    --config "$REPO_DIR/benchmarks/ahs_variants.json" \
    --set historical_open_33 \
    --variants ahs_residual_v1 \
    "$@"
