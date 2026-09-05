#!/usr/bin/env bash
set -euo pipefail

# Fixed paired experiment on the historical 33-instance residual set. Both
# variants share one binary and differ only in --population-patcher=0/1.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${AHS_PYTHON:-python3}"
if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
fi

for argument in "$@"; do
    case "$argument" in
        --config|--config=*|--instance-sets|--instance-sets=*|--set|--set=*|--instances|--instances=*|--variants|--variants=*)
            echo "run_ahs_population_ablation.sh fixes config, set, and variants; use run_ahs_benchmark.sh for overrides." >&2
            exit 2
            ;;
    esac
done

"$PYTHON_BIN" "$REPO_DIR/tools/ahs_solver.py" --policy population_cegar_only --build-only

exec "$PYTHON_BIN" "$REPO_DIR/tools/hcp_benchmark.py" \
    --config "$REPO_DIR/benchmarks/ahs_variants.json" \
    --set historical_open_33 \
    --variants ahs_cegar_only,ahs_population_cegar_only \
    "$@"
