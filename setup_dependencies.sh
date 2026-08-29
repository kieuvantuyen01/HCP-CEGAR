#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTERNAL_DIR="$REPO_DIR/external"
VENV_DIR="$REPO_DIR/.venv"
HCUP_URL="https://github.com/kieuvantuyen01/Hcup.git"
HCUP_COMMIT="bd83397877dab6d4aa44941da8743c7eb51b7437"
CRE_URL="https://github.com/kieuvantuyen01/SAT_HCP.git"
CRE_COMMIT="189af3591116bf7d87b31a1da6d6c59198f43dff"
MODE="setup"

usage() {
    cat <<'EOF'
Usage: ./setup_dependencies.sh [--no-build | --check]

  no argument  clone pinned external sources, create .venv, install PySAT,
               and build the CEGAR/HCup backends
  --no-build   clone sources and install PySAT, but do not compile Rust/C++
  --check      make no changes; verify sources, Python dependency and binaries
EOF
}

case "${1:-}" in
    "") ;;
    --no-build) MODE="no-build" ;;
    --check) MODE="check" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        return 1
    fi
}

check_checkout() {
    local directory="$1"
    local expected_commit="$2"
    local label="$3"
    if [[ ! -d "$directory/.git" ]]; then
        echo "$label source is missing: $directory" >&2
        return 1
    fi
    local actual_commit
    actual_commit="$(git -C "$directory" rev-parse HEAD)"
    if [[ "$actual_commit" != "$expected_commit" && "$actual_commit" != "$expected_commit"* ]]; then
        echo "$label is at $actual_commit, expected $expected_commit" >&2
        return 1
    fi
}

clone_pinned() {
    local url="$1"
    local commit="$2"
    local directory="$3"
    local label="$4"
    if [[ -e "$directory" && ! -d "$directory/.git" ]]; then
        echo "Refusing to overwrite non-Git path: $directory" >&2
        exit 1
    fi
    if [[ ! -d "$directory/.git" ]]; then
        git clone --recurse-submodules "$url" "$directory"
    fi
    if [[ -n "$(git -C "$directory" status --porcelain)" ]]; then
        echo "Refusing to change dirty managed checkout: $directory" >&2
        exit 1
    fi
    git -C "$directory" fetch origin "$commit"
    git -C "$directory" checkout --detach "$commit"
    git -C "$directory" submodule update --init --recursive
    check_checkout "$directory" "$commit" "$label"
}

require_command git
require_command python3

if [[ "$MODE" == "check" ]]; then
    check_checkout "$EXTERNAL_DIR/hcup" "$HCUP_COMMIT" "HCup"
    check_checkout "$EXTERNAL_DIR/SAT_HCP" "$CRE_COMMIT" "CRE"
    [[ -x "$VENV_DIR/bin/python" ]] || { echo "Missing Python environment: $VENV_DIR" >&2; exit 1; }
    "$VENV_DIR/bin/python" -c 'from pysat.solvers import Cadical195'
    [[ -x "$REPO_DIR/src/cegar-ffi/target/release/cegar-ffi" ]] || { echo "CEGAR binary is not built" >&2; exit 1; }
    [[ -x "$EXTERNAL_DIR/hcup/cmake-build-release/hcup" ]] || { echo "HCup binary is not built" >&2; exit 1; }
    echo "All pinned sources, Python dependencies, and solver binaries are ready."
    exit 0
fi

mkdir -p "$EXTERNAL_DIR"
clone_pinned "$HCUP_URL" "$HCUP_COMMIT" "$EXTERNAL_DIR/hcup" "HCup"
clone_pinned "$CRE_URL" "$CRE_COMMIT" "$EXTERNAL_DIR/SAT_HCP" "CRE"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$REPO_DIR/requirements-cre.txt"
"$VENV_DIR/bin/python" -c 'from pysat.solvers import Cadical195'

if [[ "$MODE" == "no-build" ]]; then
    echo "Sources and Python dependencies are ready; native solver build was skipped."
    exit 0
fi

require_command cargo
require_command cmake
"$REPO_DIR/run_ahs.sh" --policy rule_v1 --build-only
"$REPO_DIR/setup_dependencies.sh" --check
