#!/usr/bin/env python3
"""Analyze HCP benchmark JSONL with paired, censored, and family-aware metrics."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SAT = "SATISFIABLE"


def load_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number}: {error}") from error
    return rows


def is_solved(row: dict[str, Any]) -> bool:
    return row.get("status") == SAT and row.get("verified") is True


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def geometric_mean(values: list[float]) -> float | None:
    positive = [value for value in values if value > 0]
    return math.exp(sum(math.log(value) for value in positive) / len(positive)) if positive else None


def aggregate(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    grouped: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["variant"], int(row["graph_number"]))].append(row)
    result = {}
    for key, repeats in grouped.items():
        solved_repeats = [row for row in repeats if is_solved(row)]
        stable_solved = len(solved_repeats) == len(repeats)
        result[key] = {
            "variant": key[0],
            "graph_number": key[1],
            "repetitions": len(repeats),
            "stable_solved": stable_solved,
            "solved_repetitions": len(solved_repeats),
            "wall_sec": median([float(row["wall_sec"]) for row in solved_repeats]) if stable_solved else None,
            "timeout_sec": float(repeats[0]["timeout_sec"]),
            "features": repeats[0].get("graph_features", {}),
            "statuses": dict(Counter(row["status"] for row in repeats)),
        }
    return result


def format_float(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def variant_summary(rows: list[dict[str, Any]], par_factor: float) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["variant"]].append(row)
    summaries = []
    for variant, records in sorted(grouped.items()):
        solved = [row for row in records if is_solved(row)]
        penalties = [
            float(row["wall_sec"])
            if is_solved(row)
            else par_factor * float(row["timeout_sec"])
            for row in records
        ]
        summaries.append(
            {
                "variant": variant,
                "runs": len(records),
                "solved": len(solved),
                "timeout": sum(row["status"] == "TIMEOUT" for row in records),
                "bad": sum(row["status"] not in (SAT, "TIMEOUT", "UNKNOWN") for row in records),
                "median_sat": median([float(row["wall_sec"]) for row in solved]),
                "par": sum(penalties) / len(penalties),
            }
        )
    return summaries


def compare_variants(
    agg: dict[tuple[str, int], dict[str, Any]], baseline: str, candidate: str
) -> dict[str, Any]:
    graph_numbers = sorted(
        set(graph for variant, graph in agg if variant == baseline)
        & set(graph for variant, graph in agg if variant == candidate)
    )
    regressions = []
    gains = []
    jointly_solved = []
    ratios = []
    family = defaultdict(lambda: Counter())
    for graph_number in graph_numbers:
        base = agg[(baseline, graph_number)]
        cand = agg[(candidate, graph_number)]
        base_sat = base["stable_solved"]
        cand_sat = cand["stable_solved"]
        family_name = cand["features"].get("family", "unknown")
        if base_sat and not cand_sat:
            regressions.append(graph_number)
            family[family_name]["regression"] += 1
        elif cand_sat and not base_sat:
            gains.append(graph_number)
            family[family_name]["gain"] += 1
        elif base_sat and cand_sat:
            ratio = float(cand["wall_sec"]) / max(float(base["wall_sec"]), 1e-9)
            jointly_solved.append(graph_number)
            ratios.append(ratio)
            family[family_name]["joint"] += 1
            family[family_name]["faster"] += ratio < 1.0
            family[family_name]["slower"] += ratio > 1.0
    return {
        "graphs": graph_numbers,
        "regressions": regressions,
        "gains": gains,
        "jointly_solved": jointly_solved,
        "ratios": ratios,
        "geomean_ratio": geometric_mean(ratios),
        "median_ratio": median(ratios),
        "faster": sum(ratio < 1.0 for ratio in ratios),
        "slower": sum(ratio > 1.0 for ratio in ratios),
        "family": family,
    }


def load_paper_csv(path: Path, column: str) -> dict[int, float | None]:
    result: dict[int, float | None] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if column not in (reader.fieldnames or []):
            raise KeyError(f"column {column!r} not found; choices: {reader.fieldnames}")
        first_column = reader.fieldnames[0]
        for row in reader:
            graph_number = int(row[first_column])
            raw_value = row[column].strip()
            result[graph_number] = None if raw_value.upper() == "TO" else float(raw_value)
    return result


def paper_comparison(
    agg: dict[tuple[str, int], dict[str, Any]], variant: str, paper: dict[int, float | None]
) -> dict[str, Any]:
    available = sorted(graph for (name, graph) in agg if name == variant and graph in paper)
    regressions = []
    gains = []
    joint_ratios = []
    for graph in available:
        current = agg[(variant, graph)]
        paper_time = paper[graph]
        if paper_time is not None and not current["stable_solved"]:
            regressions.append(graph)
        elif paper_time is None and current["stable_solved"]:
            gains.append(graph)
        elif paper_time is not None and current["stable_solved"]:
            joint_ratios.append(float(current["wall_sec"]) / max(paper_time, 1e-9))
    return {
        "available": available,
        "regressions": regressions,
        "gains": gains,
        "joint_ratios": joint_ratios,
    }


def build_markdown(
    rows: list[dict[str, Any]],
    baseline: str | None,
    candidate: str | None,
    par_factor: float,
    paper_result: dict[str, Any] | None,
    paper_column: str | None,
) -> str:
    lines = ["# HCP benchmark analysis", ""]
    lines.append(f"Runs: {len(rows)}; generated from verified JSONL records. PAR factor: {par_factor:g}.")
    lines.extend(["", "## Variant summary", ""])
    lines.append("| Variant | Runs | Verified SAT | Timeout | Invalid/error | Median SAT (s) | PAR |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for summary in variant_summary(rows, par_factor):
        lines.append(
            f"| {summary['variant']} | {summary['runs']} | {summary['solved']} | "
            f"{summary['timeout']} | {summary['bad']} | {format_float(summary['median_sat'])} | "
            f"{format_float(summary['par'])} |"
        )

    if baseline and candidate:
        comparison = compare_variants(aggregate(rows), baseline, candidate)
        lines.extend(["", f"## Paired: {candidate} vs {baseline}", ""])
        lines.append(
            f"Common graphs: {len(comparison['graphs'])}; gains: {len(comparison['gains'])}; "
            f"regressions: {len(comparison['regressions'])}; jointly solved: {len(comparison['jointly_solved'])}."
        )
        lines.append(
            f"On jointly solved graphs: {comparison['faster']} faster, {comparison['slower']} slower; "
            f"geometric-mean ratio current/baseline = {format_float(comparison['geomean_ratio'])}; "
            f"median ratio = {format_float(comparison['median_ratio'])}."
        )
        lines.extend(
            [
                "",
                f"- Gains: {', '.join(f'graph{n}' for n in comparison['gains']) or 'none'}",
                "",
                f"- Regressions: {', '.join(f'graph{n}' for n in comparison['regressions']) or 'none'}",
                "",
                "| Family | Gains | Regressions | Joint | Faster | Slower |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for family_name, counts in sorted(comparison["family"].items()):
            lines.append(
                f"| {family_name} | {counts['gain']} | {counts['regression']} | "
                f"{counts['joint']} | {counts['faster']} | {counts['slower']} |"
            )

    if paper_result is not None:
        lines.extend(["", f"## Compared with paper CSV: {paper_column}", ""])
        lines.append(
            f"Comparable graphs: {len(paper_result['available'])}; current gains: {len(paper_result['gains'])}; "
            f"current regressions: {len(paper_result['regressions'])}."
        )
        lines.extend(
            [
                "",
                f"- Gains: {', '.join(f'graph{n}' for n in paper_result['gains']) or 'none'}",
                "",
                f"- Regressions: {', '.join(f'graph{n}' for n in paper_result['regressions']) or 'none'}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--baseline")
    parser.add_argument("--candidate")
    parser.add_argument("--par-factor", type=float, default=2.0)
    parser.add_argument("--paper-csv", type=Path)
    parser.add_argument(
        "--paper-column",
        default="asp2-fix-2loop-2opt3-cadical-sinz",
        help="Paper CSV solver column (937-solved single configuration by default)",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = load_jsonl([path.resolve() for path in args.results])
    agg = aggregate(rows)
    paper_result = None
    if args.paper_csv:
        if not args.candidate:
            raise ValueError("--paper-csv requires --candidate")
        paper = load_paper_csv(args.paper_csv.resolve(), args.paper_column)
        paper_result = paper_comparison(agg, args.candidate, paper)
    report = build_markdown(
        rows,
        args.baseline,
        args.candidate,
        args.par_factor,
        paper_result,
        args.paper_column if args.paper_csv else None,
    )
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(args.output)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
