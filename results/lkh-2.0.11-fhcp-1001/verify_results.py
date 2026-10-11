#!/usr/bin/env python3
"""Validate and summarize the filtered LKH FHCP result matrix."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Iterable


EXPECTED_GRAPHS = set(range(1, 1002))
PRIMARY_CERTIFICATE_CASES = {
    710, 717, 746, 832, 882, 950, 959, 963, 971, 975, 982, 990
}
RESIDUAL_29 = PRIMARY_CERTIFICATE_CASES | {
    788, 868, 937, 944, 951, 954, 960, 965, 966,
    974, 976, 981, 983, 987, 993, 994, 998,
}
REQUIRED_FIELDS = {
    "graph",
    "graph_number",
    "solver",
    "solver_version",
    "seed",
    "runs_parameter",
    "status",
    "verified",
    "wall_time_seconds",
    "certificate_detected_at_seconds",
    "peak_memory_mb",
    "timeout_seconds",
    "memory_limit_mb",
}


def linear_quantile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("cannot compute a quantile of an empty sequence")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def load_results(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on line {line_number}: {error}") from error
            missing = REQUIRED_FIELDS - row.keys()
            if missing:
                raise ValueError(f"line {line_number} is missing fields: {sorted(missing)}")
            rows.append(row)
    return rows


def validate(rows: list[dict[str, Any]]) -> None:
    graph_numbers = [int(row["graph_number"]) for row in rows]
    if len(graph_numbers) != 1001:
        raise ValueError(f"expected 1001 records, found {len(graph_numbers)}")
    if len(set(graph_numbers)) != len(graph_numbers):
        raise ValueError("duplicate graph numbers detected")
    observed = set(graph_numbers)
    if observed != EXPECTED_GRAPHS:
        raise ValueError(
            f"graph coverage mismatch; missing={sorted(EXPECTED_GRAPHS-observed)}, "
            f"unexpected={sorted(observed-EXPECTED_GRAPHS)}"
        )

    fixed_fields = {
        "solver": "LKH",
        "solver_version": "2.0.11",
        "seed": 1,
        "runs_parameter": 2_000_000,
        "timeout_seconds": 1800.0,
        "memory_limit_mb": 7168,
    }
    for row in rows:
        expected_name = f"graph{row['graph_number']}"
        if row["graph"] != expected_name:
            raise ValueError(f"graph label mismatch for {expected_name}")
        for field, expected in fixed_fields.items():
            if row[field] != expected:
                raise ValueError(
                    f"unexpected {field} for {expected_name}: "
                    f"{row[field]!r} != {expected!r}"
                )
        if row["status"] not in {"SATISFIABLE", "TIMEOUT"}:
            raise ValueError(f"unexpected status for {expected_name}: {row['status']}")
        if row["status"] == "SATISFIABLE" and row["verified"] is not True:
            raise ValueError(f"unverified SATISFIABLE record for {expected_name}")
        if row["status"] != "SATISFIABLE" and row["verified"] is not False:
            raise ValueError(f"non-SAT record marked verified for {expected_name}")


def compute_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    solved = [
        row for row in rows
        if row["status"] == "SATISFIABLE" and row["verified"] is True
    ]
    solved_times = [float(row["wall_time_seconds"]) for row in solved]
    solved_memory = [float(row["peak_memory_mb"]) for row in solved]
    solved_graphs = {int(row["graph_number"]) for row in solved}
    cutoff = 1800.0
    par2 = (
        sum(solved_times) + (len(rows) - len(solved)) * 2.0 * cutoff
    ) / len(rows)

    return {
        "benchmark": "FHCP Challenge Set",
        "instances": len(rows),
        "solver": "LKH",
        "solver_version": "2.0.11",
        "configuration": {
            "seed": 1,
            "runs_parameter": 2_000_000,
            "timeout_seconds": cutoff,
            "memory_limit_mb": 7168,
        },
        "outcomes": {
            "verified_satisfiable": len(solved),
            "timeout": sum(row["status"] == "TIMEOUT" for row in rows),
            "solved_by_10_seconds": sum(value <= 10.0 for value in solved_times),
            "solved_by_100_seconds": sum(value <= 100.0 for value in solved_times),
        },
        "solved_runtime_seconds": {
            "median": statistics.median(solved_times),
            "q1": linear_quantile(solved_times, 0.25),
            "q3": linear_quantile(solved_times, 0.75),
            "maximum": max(solved_times),
        },
        "solved_peak_memory_mb": {
            "median": statistics.median(solved_memory),
            "p95": linear_quantile(solved_memory, 0.95),
            "maximum": max(solved_memory),
        },
        "descriptive_par2_seconds": par2,
        "priority_cohorts": {
            "primary_certificate_cases_solved": len(
                solved_graphs & PRIMARY_CERTIFICATE_CASES
            ),
            "primary_certificate_cases_total": len(PRIMARY_CERTIFICATE_CASES),
            "residual_29_solved": len(solved_graphs & RESIDUAL_29),
            "residual_29_total": len(RESIDUAL_29),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results",
        nargs="?",
        type=Path,
        default=Path(__file__).with_name("results.jsonl"),
    )
    parser.add_argument(
        "--check-summary",
        type=Path,
        default=None,
        help="compare the computed summary with this JSON file",
    )
    args = parser.parse_args()

    rows = load_results(args.results)
    validate(rows)
    summary = compute_summary(rows)
    if args.check_summary is not None:
        expected = json.loads(args.check_summary.read_text(encoding="utf-8"))
        if summary != expected:
            raise SystemExit("computed summary does not match the supplied summary")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
