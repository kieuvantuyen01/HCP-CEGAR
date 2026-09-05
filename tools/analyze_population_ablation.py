#!/usr/bin/env python3
"""Analyze the paired population-CEGAR A/B run without flattening AHS stages."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any, Iterable


DEFAULT_BASELINE = "ahs_cegar_only"
DEFAULT_TREATMENT = "ahs_population_cegar_only"
POPULATION_SUM_FIELDS = (
    "calls",
    "parents_tried_total",
    "improvements_total",
    "budget_exhausted_calls",
    "cooldown_skipped_calls",
    "outer_rounds_total",
    "guided_rounds_total",
    "chained_lk_rounds_total",
    "round_limit_hits_total",
)


def load_results(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error
        if not isinstance(row, dict):
            raise ValueError(f"record at {path}:{line_number} is not a JSON object")
        rows.append(row)
    return rows


def stages_for_record(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return backend-stage records; direct solver rows act as their own stage."""
    stages = row.get("portfolio_stage_results")
    if isinstance(stages, list) and all(isinstance(stage, dict) for stage in stages):
        return stages
    return [row]


def is_verified_sat(row: dict[str, Any]) -> bool:
    return row.get("status") == "SATISFIABLE" and row.get("verified") is True


def reached_timeout(row: dict[str, Any]) -> bool:
    if row.get("timed_out") is True:
        return True
    for stage in stages_for_record(row):
        reason = str(stage.get("termination_reason") or "").lower()
        if (
            stage.get("timed_out") is True
            or stage.get("status") == "TIMEOUT"
            or "timeout" in reason
            or "deadline" in reason
        ):
            return True
    backend_result = row.get("backend_result")
    return isinstance(backend_result, dict) and backend_result.get("budget_exhausted") is True


def population_metrics(row: dict[str, Any]) -> dict[str, int | float]:
    metrics: dict[str, int | float] = {field: 0 for field in POPULATION_SUM_FIELDS}
    metrics.update(
        {
            "max_population_size": 0,
            "cycle_reduction_total": 0,
            "recombine_seconds": 0.0,
        }
    )
    for stage in stages_for_record(row):
        stats = stage.get("population_stats")
        if isinstance(stats, dict):
            for field in POPULATION_SUM_FIELDS:
                metrics[field] += int(stats.get(field, 0) or 0)
            metrics["max_population_size"] = max(
                int(metrics["max_population_size"]),
                int(stats.get("max_population_size", 0) or 0),
            )
        phase_stats = stage.get("phase_stats")
        if isinstance(phase_stats, dict):
            recombine = phase_stats.get("population_recombine")
            if isinstance(recombine, dict):
                metrics["cycle_reduction_total"] += int(
                    recombine.get("cycle_reduction_total", 0) or 0
                )
                metrics["recombine_seconds"] += float(recombine.get("seconds", 0.0) or 0.0)
    return metrics


def stage_metric(row: dict[str, Any], field: str) -> int | None:
    values = [stage.get(field) for stage in stages_for_record(row)]
    numeric = [int(value) for value in values if isinstance(value, (int, float))]
    return sum(numeric) if numeric else None


def index_variant(
    rows: Iterable[dict[str, Any]], variant: str
) -> dict[tuple[int, int], dict[str, Any]]:
    indexed: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        if row.get("variant") != variant:
            continue
        key = (int(row["graph_number"]), int(row.get("repetition", 1)))
        if key in indexed:
            raise ValueError(f"duplicate record for {variant}, graph{key[0]}, repetition {key[1]}")
        indexed[key] = row
    return indexed


def paired_rows(
    rows: list[dict[str, Any]], baseline: str, treatment: str
) -> tuple[list[dict[str, Any]], list[tuple[int, int]], list[tuple[int, int]]]:
    baseline_rows = index_variant(rows, baseline)
    treatment_rows = index_variant(rows, treatment)
    common = sorted(baseline_rows.keys() & treatment_rows.keys())
    baseline_only = sorted(baseline_rows.keys() - treatment_rows.keys())
    treatment_only = sorted(treatment_rows.keys() - baseline_rows.keys())
    paired: list[dict[str, Any]] = []

    for graph_number, repetition in common:
        control = baseline_rows[(graph_number, repetition)]
        trial = treatment_rows[(graph_number, repetition)]
        control_solved = is_verified_sat(control)
        trial_solved = is_verified_sat(trial)
        if control_solved and trial_solved:
            comparison = "both_solved"
        elif control_solved:
            comparison = "baseline_only"
        elif trial_solved:
            comparison = "treatment_only"
        else:
            comparison = "both_unsolved"
        telemetry = population_metrics(trial)
        paired.append(
            {
                "graph_number": graph_number,
                "repetition": repetition,
                "comparison": comparison,
                "baseline_status": control.get("status"),
                "baseline_verified": control.get("verified") is True,
                "baseline_timeout": reached_timeout(control),
                "baseline_wall_sec": float(control.get("wall_sec", 0.0) or 0.0),
                "baseline_increments": stage_metric(control, "increments"),
                "baseline_blocking_clauses": stage_metric(control, "blocking_clauses"),
                "treatment_status": trial.get("status"),
                "treatment_verified": trial.get("verified") is True,
                "treatment_timeout": reached_timeout(trial),
                "treatment_wall_sec": float(trial.get("wall_sec", 0.0) or 0.0),
                "treatment_increments": stage_metric(trial, "increments"),
                "treatment_blocking_clauses": stage_metric(trial, "blocking_clauses"),
                "wall_delta_sec": (
                    float(trial.get("wall_sec", 0.0) or 0.0)
                    - float(control.get("wall_sec", 0.0) or 0.0)
                    if control_solved and trial_solved
                    else None
                ),
                **telemetry,
            }
        )
    return paired, baseline_only, treatment_only


def variant_summary(rows: list[dict[str, Any]], variant: str) -> dict[str, int | float]:
    selected = [row for row in rows if row.get("variant") == variant]
    solved = [row for row in selected if is_verified_sat(row)]
    penalties = [
        float(row.get("wall_sec", 0.0) or 0.0)
        if is_verified_sat(row)
        else 2.0 * float(row.get("timeout_sec", 0.0) or 0.0)
        for row in selected
    ]
    return {
        "records": len(selected),
        "solved": len(solved),
        "timeouts": sum(reached_timeout(row) for row in selected),
        "par2_sec": statistics.fmean(penalties) if penalties else 0.0,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else ["graph_number", "repetition", "comparison"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, help="results.jsonl from the paired A/B run")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--treatment", default=DEFAULT_TREATMENT)
    parser.add_argument("--csv", type=Path, help="output CSV; defaults next to results.jsonl")
    args = parser.parse_args()

    results_path = args.results.resolve()
    rows = load_results(results_path)
    paired, baseline_only, treatment_only = paired_rows(
        rows, args.baseline, args.treatment
    )
    if not paired:
        raise ValueError("no paired baseline/treatment records found")
    csv_path = (
        args.csv.resolve()
        if args.csv
        else results_path.parent / "population-ablation-paired.csv"
    )
    write_csv(csv_path, paired)

    for variant in (args.baseline, args.treatment):
        summary = variant_summary(rows, variant)
        print(
            f"{variant}: solved={summary['solved']}/{summary['records']} "
            f"timeouts={summary['timeouts']} PAR-2={summary['par2_sec']:.3f}s"
        )
    print(
        "paired: "
        f"both_solved={sum(row['comparison'] == 'both_solved' for row in paired)} "
        f"baseline_only={sum(row['comparison'] == 'baseline_only' for row in paired)} "
        f"treatment_only={sum(row['comparison'] == 'treatment_only' for row in paired)} "
        f"both_unsolved={sum(row['comparison'] == 'both_unsolved' for row in paired)}"
    )

    deltas = [float(row["wall_delta_sec"]) for row in paired if row["wall_delta_sec"] is not None]
    if deltas:
        print(f"both-solved median treatment-baseline={statistics.median(deltas):.3f}s")
    treatment_totals = {
        field: sum(float(row[field]) for row in paired)
        for field in (*POPULATION_SUM_FIELDS, "cycle_reduction_total", "recombine_seconds")
    }
    active_calls = int(treatment_totals["calls"] - treatment_totals["cooldown_skipped_calls"])
    parents = int(treatment_totals["parents_tried_total"])
    improvement_rate = treatment_totals["improvements_total"] / parents if parents else 0.0
    print(
        "population: "
        f"calls={int(treatment_totals['calls'])} "
        f"active_calls={active_calls} "
        f"parents={parents} "
        f"improvements={int(treatment_totals['improvements_total'])} "
        f"improvements/parent={improvement_rate:.6f} "
        f"cycle_reduction={int(treatment_totals['cycle_reduction_total'])} "
        f"seconds={treatment_totals['recombine_seconds']:.3f} "
        f"deadline_hits={int(treatment_totals['budget_exhausted_calls'])} "
        f"cooldown_skips={int(treatment_totals['cooldown_skipped_calls'])} "
        f"round_limit_hits={int(treatment_totals['round_limit_hits_total'])}"
    )
    if baseline_only or treatment_only:
        print(
            f"warning: unpaired baseline_only={len(baseline_only)} "
            f"treatment_only={len(treatment_only)}"
        )
    print(f"CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
