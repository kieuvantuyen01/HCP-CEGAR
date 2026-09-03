#!/usr/bin/env python3
"""Run a short semantic check of every backend used by the default AHS policy."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import ahs_solver as ahs
import hcp_benchmark as runner


def main() -> int:
    config = ahs.load_config(ahs.DEFAULT_CONFIG)
    policy = config["default_policy"]
    indexed = ahs.backend_index(config)
    graph = ahs.ROOT / "FHCPCS-col" / "graph1.col"
    _, vertices, edges = runner.graph_features(graph)
    env = os.environ.copy()
    env.update(ahs.CONTROLLED_ENV)

    with tempfile.TemporaryDirectory(prefix="ahs-backend-smoke-") as directory:
        temp = Path(directory)
        for name in ahs.policy_backend_names(config, policy):
            backend = indexed[name]
            binary = ahs.expected_binary(backend)
            if not binary.is_file():
                raise FileNotFoundError(f"backend is not built: {binary}")
            result, _ = ahs.run_stage(
                backend,
                binary,
                graph,
                30.0,
                vertices,
                edges,
                temp / f"{runner.safe_name(name)}.txt",
                env,
            )
            if result["status"] != "SATISFIABLE" or not result["verified"]:
                raw = Path(result["raw_log"]).read_text(encoding="utf-8", errors="replace")
                print(raw[-4000:], file=sys.stderr)
                raise RuntimeError(
                    f"semantic smoke failed for {name}: "
                    f"status={result['status']} reason={result['verification_reason']}"
                )
            print(f"backend-smoke {name}: verified ({result['wall_sec']:.3f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
