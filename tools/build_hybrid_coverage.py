#!/usr/bin/env python3
"""Build an auditable per-instance coverage inventory for the FHCP dataset.

The report deliberately separates three concepts:

* a real single solver configuration;
* a static portfolio of several configurations; and
* a virtual best solver (VBS) that chooses retrospectively per instance.

Missing evidence is always written as ``MISSING``.  In particular, an interrupted
console log is never interpreted as a timeout for tasks that did not finish.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from hcp_benchmark import graph_features


ROOT = Path(__file__).resolve().parents[1]
DATASET_SIZE = 1001
SOLVED = "SOLVED"
TIMEOUT = "TIMEOUT"
MISSING = "MISSING"
INCOMPLETE = "INCOMPLETE"

PAPER_CSV_SOURCES = (
    (
        ROOT / "logs/existing-work.csv",
        "reference_solver",
        {
            "adder": "ref_adder",
            "crt-420": "ref_crt_420",
            "existing-cegar-fix-2loop-cadical-sinz": "ref_cegar_old_2loop_cadical_sinz",
            "asp": "ref_asp",
            "picat": "ref_picat",
        },
    ),
    (
        ROOT / "logs/proposed-cegar-ccadical-cpu.csv",
        "paper_cegar_ccadical",
        {
            "proposed-cegar-ffi-cadical": "ccad_base",
            "proposed-cegar-ffi-2loop-cadical": "ccad_2loop",
            "proposed-cegar-ffi-lowest-asymmetry3-cadical": "ccad_asym3",
            "proposed-cegar-ffi-2opt3-cadical": "ccad_2opt3",
            "proposed-cegar-ffi-2loop-lowest-asymmetry3-cadical": "ccad_2loop_asym3",
            "proposed-cegar-ffi-lowest-asymmetry3-2opt3-cadical": "ccad_asym3_2opt3",
            "proposed-cegar-ffi-2loop-2opt3-cadical": "ccad_2loop_2opt3",
            "proposed-cegar-ffi-2loop-lowest-asymmetry3-2opt3-cadical": "ccad_2loop_asym3_2opt3",
        },
    ),
    (
        ROOT / "logs/proposed-cegar-sinz-cpu.csv",
        "paper_cegar_sinz",
        {
            "asp2-fix-cadical-sinz": "sinz_base",
            "asp2-fix-2loop-cadical-sinz": "sinz_2loop",
            "asp2-fix-lowest-asymmetry2-cadical-sinz": "sinz_asym2",
            "asp2-fix-2opt3-cadical-sinz": "sinz_2opt3",
            "asp2-fix-2loop-lowest-asymmetry2-cadical-sinz": "sinz_2loop_asym2",
            "asp2-fix-lowest-asymmetry2-2opt3-cadical-sinz": "sinz_asym2_2opt3",
            "asp2-fix-2loop-2opt3-cadical-sinz": "sinz_2loop_2opt3",
            "asp2-fix-2loop-lowest-asymmetry2-2opt3-cadical-sinz": "sinz_2loop_asym2_2opt3",
        },
    ),
)

# Greedy four-stage portfolio that reaches the full 968-instance union of all
# 21 per-instance paper/reference configurations.
PORTFOLIO_ORDER = (
    "ccad_2loop_asym3_2opt3",
    "ref_asp",
    "sinz_2loop",
    "ref_picat",
)

def aggregate_method(
    method_id: str,
    display_name: str,
    family: str,
    solved: int,
    timeout: int | None,
    oom: int | None,
    abort: int | None = 0,
    notes: str = "Per-instance logs unavailable locally.",
) -> dict[str, Any]:
    return {
        "method_id": method_id,
        "display_name": display_name,
        "family": family,
        "reported_solved": solved,
        "reported_timeout": timeout,
        "reported_oom": oom,
        "reported_abort": abort,
        "notes": notes,
    }


# Aggregate-only rows transcribed from Tables 5.2 and 5.3 of the HCup paper.
# They are intentionally not used for per-instance unions: totals alone do not
# reveal which graphs overlap with the older 21 configurations.
HCUP_AGGREGATES = (
    aggregate_method("hcup_paper_cegarfix_asym", "cegar-fix -asym", "hcup_cegar_comparison", 928, 71, 0, 2),
    aggregate_method("hcup_paper_cegarfix_2loop", "cegar-fix +2loop", "hcup_cegar_comparison", 824, 87, 0, 90),
    aggregate_method("hcup_cegar_outside_allcutset", "HCup outside-allcutset", "hcup_cegar_aggregate", 843, 157, 1),
    aggregate_method("hcup_cegar_outside_allsubcycle", "HCup outside-allsubcycle", "hcup_cegar_aggregate", 590, 321, 90),
    aggregate_method(
        "hcup_cegar_outside_mergecutset",
        "HCup outside-mergecutset",
        "hcup_cegar_aggregate",
        937,
        64,
        0,
        notes="Full CEGAR with inprocessing; per-instance logs unavailable locally.",
    ),
    aggregate_method("hcup_cegar_outside_paircutsetbal", "HCup outside-paircutsetbal", "hcup_cegar_aggregate", 399, 545, 57),
    aggregate_method("hcup_cegar_outside_paircutsetoa", "HCup outside-paircutsetoa", "hcup_cegar_aggregate", 754, 247, 0),
    aggregate_method(
        "hcup_cegar_outside_mergecutset_plain",
        "HCup outside-mergecutset-plain",
        "hcup_cegar_aggregate",
        820,
        145,
        36,
        notes="No inprocessing; per-instance logs unavailable locally.",
    ),
    aggregate_method(
        "hcup_vbs_cegar",
        "HCup VBS-cegar",
        "hcup_virtual_best_aggregate",
        943,
        None,
        None,
        None,
        "Virtual/oracle result, not a runnable single configuration; per-instance logs unavailable locally.",
    ),
    aggregate_method("hcup_inside_allcutset", "HCup inside-allcutset", "hcup_propagator_aggregate", 813, 130, 58),
    aggregate_method("hcup_inside_allsubcycle", "HCup inside-allsubcycle", "hcup_propagator_aggregate", 461, 279, 261),
    aggregate_method("hcup_inside_mergecutset", "HCup inside-mergecutset", "hcup_propagator_aggregate", 871, 114, 16),
    aggregate_method("hcup_inside_paircutsetbal", "HCup inside-paircutsetbal", "hcup_propagator_aggregate", 284, 357, 360),
    aggregate_method("hcup_inside_paircutsetoa", "HCup inside-paircutsetoa", "hcup_propagator_aggregate", 735, 204, 62),
    aggregate_method("hcup_ecd_subcycle", "HCup ecd-subcycle", "hcup_propagator_aggregate", 477, 350, 174),
    aggregate_method("hcup_ecd_cutset", "HCup ecd-cutset", "hcup_propagator_aggregate", 792, 112, 97),
    aggregate_method("hcup_ecd_cutset_subcycle", "HCup ecd-cutset+subcycle", "hcup_propagator_aggregate", 787, 106, 108),
    aggregate_method("hcup_hfp_heat", "HCup hfp-heat", "hcup_propagator_aggregate", 842, 100, 59),
    aggregate_method(
        "hcup_hfp_preventsubcycle",
        "HCup hfp-preventsubcycle",
        "hcup_propagator_aggregate",
        917,
        84,
        0,
        notes="Best single user-propagator configuration; per-instance logs unavailable locally.",
    ),
    aggregate_method("hcup_hfp_cutset_heat", "HCup hfp-cutset-heat", "hcup_propagator_aggregate", 807, 110, 84),
    aggregate_method("hcup_hfp_cutset_preventsubcycle", "HCup hfp-cutset-preventsubcycle", "hcup_propagator_aggregate", 754, 128, 119),
    aggregate_method("hcup_lfp_cutset25", "HCup lfp-cutset25", "hcup_propagator_aggregate", 817, 111, 73),
    aggregate_method("hcup_lfp_cutset35", "HCup lfp-cutset35", "hcup_propagator_aggregate", 832, 83, 86),
    aggregate_method("hcup_lfp_cutset75", "HCup lfp-cutset75", "hcup_propagator_aggregate", 834, 91, 76),
    aggregate_method("hcup_lfp_mergecutset25", "HCup lfp-mergecutset25", "hcup_propagator_aggregate", 807, 98, 96),
    aggregate_method("hcup_lfp_mergecutset35", "HCup lfp-mergecutset35", "hcup_propagator_aggregate", 804, 104, 93),
    aggregate_method("hcup_lfp_mergecutset75", "HCup lfp-mergecutset75", "hcup_propagator_aggregate", 829, 80, 92),
    aggregate_method(
        "hcup_vbs_propagator",
        "HCup VBS-propagator",
        "hcup_virtual_best_aggregate",
        961,
        None,
        None,
        None,
        "Virtual/oracle result, not a runnable single configuration; per-instance logs unavailable locally.",
    ),
)

STATUS_RANK = {
    MISSING: 0,
    INCOMPLETE: 1,
    "ERROR": 2,
    "UNKNOWN": 2,
    "UNSATISFIABLE": 2,
    "INVALID_SAT": 2,
    TIMEOUT: 3,
    SOLVED: 4,
}


@dataclass
class MethodInfo:
    method_id: str
    display_name: str
    family: str
    source_path: str
    timeout_sec: float | None
    per_instance_available: bool = True
    notes: str = ""
    reported_solved: int | None = None
    reported_timeout: int | None = None
    reported_oom: int | None = None
    reported_abort: int | None = None


@dataclass
class Observation:
    graph_number: int
    method_id: str
    status: str
    time_sec: float | None
    timeout_sec: float | None
    verified: bool | None
    source_path: str
    notes: str = ""


@dataclass
class CoverageData:
    methods: dict[str, MethodInfo] = field(default_factory=dict)
    observations: list[Observation] = field(default_factory=list)
    paper_method_ids: list[str] = field(default_factory=list)
    baseline_timeout_class: dict[int, str] = field(default_factory=dict)

    def register(self, method: MethodInfo) -> None:
        current = self.methods.get(method.method_id)
        if current is None:
            self.methods[method.method_id] = method
            return
        if current.family != method.family:
            raise ValueError(
                f"method id collision for {method.method_id}: "
                f"{current.family!r} vs {method.family!r}"
            )


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def normalize_status(value: str) -> str:
    status = value.strip().upper()
    if status in {"SATISFIABLE", SOLVED}:
        return SOLVED
    if status == TIMEOUT:
        return TIMEOUT
    if status in {MISSING, INCOMPLETE}:
        return status
    if status.startswith("ERROR") or status.startswith("EXIT_") or status.startswith("EXCEPTION"):
        return "ERROR"
    return status or "UNKNOWN"


def parse_paper_csvs(data: CoverageData) -> None:
    for path, family, aliases in PAPER_CSV_SOURCES:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != DATASET_SIZE:
            raise ValueError(f"expected {DATASET_SIZE} rows in {path}, got {len(rows)}")
        graph_key = next(iter(rows[0]))
        for raw_name, method_id in aliases.items():
            if raw_name not in rows[0]:
                raise KeyError(f"column {raw_name!r} missing from {path}")
            data.register(
                MethodInfo(
                    method_id=method_id,
                    display_name=raw_name,
                    family=family,
                    source_path=relpath(path),
                    timeout_sec=1800.0,
                    notes="CPU seconds; TO means timeout at the 1800-second paper cap.",
                )
            )
            data.paper_method_ids.append(method_id)
            for row in rows:
                graph_number = int(row[graph_key])
                raw_value = row[raw_name].strip()
                status = TIMEOUT if raw_value == "TO" else SOLVED
                runtime = None if status == TIMEOUT else float(raw_value)
                data.observations.append(
                    Observation(
                        graph_number=graph_number,
                        method_id=method_id,
                        status=status,
                        time_sec=runtime,
                        timeout_sec=1800.0,
                        verified=None,
                        source_path=relpath(path),
                        notes="Published per-instance CPU time; tour verification not recorded in CSV.",
                    )
                )


def parse_baseline_timeout_classes(path: Path) -> dict[int, str]:
    classes: dict[int, str] = {}
    pattern = re.compile(r"^\|\s*graph(\d+)\s*\|\s*(A|B1|B2a|B2b)\s*\|")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if match:
            classes[int(match.group(1))] = match.group(2)
    if len(classes) != 75:
        raise ValueError(f"expected 75 baseline timeout rows in {path}, got {len(classes)}")
    return classes


def parse_derived_official_baseline(data: CoverageData) -> None:
    path = ROOT / "docs/timeout-classification-analysis.md"
    classes = parse_baseline_timeout_classes(path)
    data.baseline_timeout_class = classes
    method_id = "current_official_baseline_1800"
    data.register(
        MethodInfo(
            method_id=method_id,
            display_name="Current official baseline (derived status)",
            family="current_official_baseline",
            source_path=relpath(path),
            timeout_sec=1800.0,
            notes=(
                "Status reconstructed from the documented 75-timeout list; "
                "the raw 1001-instance log is not present locally."
            ),
        )
    )
    for graph_number in range(1, DATASET_SIZE + 1):
        status = TIMEOUT if graph_number in classes else SOLVED
        data.observations.append(
            Observation(
                graph_number=graph_number,
                method_id=method_id,
                status=status,
                time_sec=None,
                timeout_sec=1800.0,
                verified=None,
                source_path=relpath(path),
                notes="Derived status only; per-instance runtime omitted.",
            )
        )


def configured_current_variants() -> list[str]:
    path = ROOT / "benchmarks/ablation_variants.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [str(item["name"]) for item in payload["variants"]]


def parse_regression_console(data: CoverageData, path: Path | None) -> None:
    variants = configured_current_variants()
    for variant in variants:
        method_id = f"current300_{variant}"
        data.register(
            MethodInfo(
                method_id=method_id,
                display_name=f"current 300s / {variant}",
                family="current_regression_300s",
                source_path=relpath(path) if path else "not_supplied",
                timeout_sec=300.0,
                notes="Paired regression run; only completed task/result pairs are observations.",
            )
        )
    if path is None or not path.is_file():
        return

    header_re = re.compile(
        r"^\[(?P<task>\d+)/(?P<total>\d+)\]\s+"
        r"(?P<variant>\S+)\s+graph(?P<graph>\d+)\s+r(?P<repetition>\d+)\s*$"
    )
    result_re = re.compile(
        r"^\s*->\s+(?P<status>\S+)\s+(?P<seconds>[0-9.]+)s\s+"
        r"verified=(?P<verified>True|False)\s+\((?P<reason>.*)\)\s*$"
    )
    pending: dict[str, Any] | None = None

    def append_incomplete(item: dict[str, Any]) -> None:
        data.observations.append(
            Observation(
                graph_number=item["graph"],
                method_id=f"current300_{item['variant']}",
                status=INCOMPLETE,
                time_sec=None,
                timeout_sec=300.0,
                verified=None,
                source_path=relpath(path),
                notes=f"Task {item['task']}/{item['total']} started but has no result line.",
            )
        )

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        header = header_re.match(line)
        if header:
            if pending is not None:
                append_incomplete(pending)
            pending = {
                "task": int(header.group("task")),
                "total": int(header.group("total")),
                "variant": header.group("variant"),
                "graph": int(header.group("graph")),
                "repetition": int(header.group("repetition")),
            }
            method_id = f"current300_{pending['variant']}"
            if method_id not in data.methods:
                data.register(
                    MethodInfo(
                        method_id=method_id,
                        display_name=f"current 300s / {pending['variant']}",
                        family="current_regression_300s",
                        source_path=relpath(path),
                        timeout_sec=300.0,
                    )
                )
            continue
        result = result_re.match(line)
        if result and pending is not None:
            status = normalize_status(result.group("status"))
            verified = result.group("verified") == "True"
            data.observations.append(
                Observation(
                    graph_number=pending["graph"],
                    method_id=f"current300_{pending['variant']}",
                    status=status,
                    time_sec=float(result.group("seconds")),
                    timeout_sec=300.0,
                    verified=verified,
                    source_path=relpath(path),
                    notes=(
                        f"task={pending['task']}/{pending['total']}; "
                        f"repetition={pending['repetition']}; {result.group('reason')}"
                    ),
                )
            )
            pending = None
    if pending is not None:
        append_incomplete(pending)


def parse_legacy_jsons(data: CoverageData) -> None:
    benchmark_path = ROOT / "logs/benchmark_100_results.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    method_id = "legacy_current_sample_15s"
    data.register(
        MethodInfo(
            method_id=method_id,
            display_name="Legacy current build, graph10..1000 sample",
            family="legacy_current_sample",
            source_path=relpath(benchmark_path),
            timeout_sec=15.0,
            notes="Old build 4d094b7; 100 sampled graphs only.",
        )
    )
    for row in benchmark["results"]:
        graph_number = int(re.search(r"\d+", row["graph"]).group())
        data.observations.append(
            Observation(
                graph_number=graph_number,
                method_id=method_id,
                status=normalize_status(row["status"]),
                time_sec=float(row["time"]),
                timeout_sec=15.0,
                verified=None,
                source_path=relpath(benchmark_path),
                notes=str(row.get("notes", "")),
            )
        )

    stem_path = ROOT / "logs/stem_cycle_patcher_results.json"
    stem = json.loads(stem_path.read_text(encoding="utf-8"))
    method_id = "stem_cycle_patcher_checkpoint"
    data.register(
        MethodInfo(
            method_id=method_id,
            display_name="Stem-cycle patcher checkpoint",
            family="current_experimental_checkpoint",
            source_path=relpath(stem_path),
            timeout_sec=1800.0,
            notes="Checkpoint stopped after 40 graphs; missing rows were never run.",
        )
    )
    for graph_name, row in stem["results"].items():
        graph_number = int(re.search(r"\d+", graph_name).group())
        data.observations.append(
            Observation(
                graph_number=graph_number,
                method_id=method_id,
                status=normalize_status(row["status"]),
                time_sec=float(row["time_sec"]),
                timeout_sec=1800.0,
                verified=None,
                source_path=relpath(stem_path),
                notes="Checkpoint result; tour verification flag not recorded.",
            )
        )


def parse_runner_jsonl(data: CoverageData, paths: Iterable[Path]) -> None:
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            variant = str(row["variant"])
            method_id = f"runner_{re.sub(r'[^A-Za-z0-9_.-]+', '_', variant)}"
            timeout_sec = float(row.get("timeout_sec", 1800.0))
            data.register(
                MethodInfo(
                    method_id=method_id,
                    display_name=f"runner / {variant}",
                    family="reproducible_runner_jsonl",
                    source_path=relpath(path),
                    timeout_sec=timeout_sec,
                    notes="Imported from hcp_benchmark.py results.jsonl.",
                )
            )
            raw_status = str(row.get("status", row.get("solver_status", "UNKNOWN")))
            status = normalize_status(raw_status)
            data.observations.append(
                Observation(
                    graph_number=int(row["graph_number"]),
                    method_id=method_id,
                    status=status,
                    time_sec=float(row["wall_sec"]) if row.get("wall_sec") is not None else None,
                    timeout_sec=timeout_sec,
                    verified=row.get("verified"),
                    source_path=relpath(path),
                    notes=f"line={line_number}; solver_status={row.get('solver_status')}",
                )
            )


def register_hcup_aggregates(data: CoverageData) -> None:
    source = ROOT.parent / "Funder Fabian - 2026 - An UPgrade for HCP Solving the Hamiltonian Cycle Problem.pdf"
    for item in HCUP_AGGREGATES:
        data.register(
            MethodInfo(
                method_id=str(item["method_id"]),
                display_name=str(item["display_name"]),
                family=str(item["family"]),
                source_path=relpath(source),
                timeout_sec=1800.0,
                per_instance_available=False,
                notes=str(item["notes"]),
                reported_solved=int(item["reported_solved"]),
                reported_timeout=(
                    int(item["reported_timeout"])
                    if item["reported_timeout"] is not None
                    else None
                ),
                reported_oom=(
                    int(item["reported_oom"])
                    if item["reported_oom"] is not None
                    else None
                ),
                reported_abort=(
                    int(item["reported_abort"])
                    if item["reported_abort"] is not None
                    else None
                ),
            )
        )


def load_coverage_data(
    regression_console: Path | None,
    runner_jsonls: Iterable[Path] = (),
) -> CoverageData:
    data = CoverageData()
    parse_paper_csvs(data)
    parse_derived_official_baseline(data)
    parse_regression_console(data, regression_console)
    parse_legacy_jsons(data)
    parse_runner_jsonl(data, runner_jsonls)
    register_hcup_aggregates(data)
    return data


def preferred_observation(current: Observation | None, candidate: Observation) -> Observation:
    if current is None:
        return candidate
    current_rank = STATUS_RANK.get(current.status, 2)
    candidate_rank = STATUS_RANK.get(candidate.status, 2)
    if candidate_rank != current_rank:
        return candidate if candidate_rank > current_rank else current
    if candidate.status == SOLVED:
        current_time = current.time_sec if current.time_sec is not None else float("inf")
        candidate_time = candidate.time_sec if candidate.time_sec is not None else float("inf")
        return candidate if candidate_time < current_time else current
    return current


def observation_index(data: CoverageData) -> dict[tuple[int, str], Observation]:
    indexed: dict[tuple[int, str], Observation] = {}
    for observation in data.observations:
        key = (observation.graph_number, observation.method_id)
        indexed[key] = preferred_observation(indexed.get(key), observation)
    return indexed


def fastest_solved(
    graph_number: int,
    method_ids: Iterable[str],
    indexed: dict[tuple[int, str], Observation],
) -> Observation | None:
    solved = [
        indexed[(graph_number, method_id)]
        for method_id in method_ids
        if (graph_number, method_id) in indexed
        and indexed[(graph_number, method_id)].status == SOLVED
    ]
    if not solved:
        return None
    return min(
        solved,
        key=lambda item: item.time_sec if item.time_sec is not None else float("inf"),
    )


def minimum_portfolio_for_full_union(
    method_ids: Iterable[str],
    indexed: dict[tuple[int, str], Observation],
) -> tuple[tuple[str, ...], set[int]]:
    methods = list(method_ids)
    solved_by_method = {
        method_id: {
            graph_number
            for graph_number in range(1, DATASET_SIZE + 1)
            if indexed.get((graph_number, method_id)) is not None
            and indexed[(graph_number, method_id)].status == SOLVED
        }
        for method_id in methods
    }
    target = set().union(*solved_by_method.values())
    for size in range(1, len(methods) + 1):
        for selected in combinations(methods, size):
            if set().union(*(solved_by_method[method_id] for method_id in selected)) == target:
                return selected, target
    return (), target


def format_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def open_instance_recommendation(timeout_class: str) -> str:
    return {
        "B1": "HCup full + hfp; then dense-module/decomposition hybrid",
        "B2a": "HCup hfp; then global patching/connectivity formulation",
        "B2b": "HCup full + hfp; then encoding/phase portfolio with long-call telemetry",
        "A": "blocking-clause/cut-arc escape portfolio",
    }.get(timeout_class, "paired HCup/full-current benchmark")


def build_instance_rows(
    data: CoverageData,
    indexed: dict[tuple[int, str], Observation],
) -> tuple[list[dict[str, Any]], list[str]]:
    per_instance_method_ids = [
        method_id
        for method_id, method in data.methods.items()
        if method.per_instance_available
    ]
    status_columns = [f"status__{method_id}" for method_id in per_instance_method_ids]
    rows: list[dict[str, Any]] = []
    graph_dir = ROOT / "FHCPCS-col"
    current_methods = [
        method_id
        for method_id, method in data.methods.items()
        if method.family == "current_regression_300s"
    ]
    imported_hcup_methods = [
        method_id
        for method_id, method in data.methods.items()
        if method.family == "reproducible_runner_jsonl" and method_id.startswith("runner_hcup_")
    ]
    paper_methods = list(data.paper_method_ids)

    for graph_number in range(1, DATASET_SIZE + 1):
        features, _, _ = graph_features(graph_dir / f"graph{graph_number}.col")
        all_fastest = fastest_solved(graph_number, per_instance_method_ids, indexed)
        paper_fastest = fastest_solved(graph_number, paper_methods, indexed)
        current_fastest = fastest_solved(graph_number, current_methods, indexed)
        solved_methods = [
            method_id
            for method_id in per_instance_method_ids
            if indexed.get((graph_number, method_id), None) is not None
            and indexed[(graph_number, method_id)].status == SOLVED
        ]
        current_observed = [
            indexed[(graph_number, method_id)]
            for method_id in current_methods
            if (graph_number, method_id) in indexed
        ]
        hcup_observed = [
            indexed[(graph_number, method_id)]
            for method_id in imported_hcup_methods
            if (graph_number, method_id) in indexed
        ]

        portfolio_stage = "OPEN"
        portfolio_method = ""
        portfolio_time = ""
        for stage, method_id in enumerate(PORTFOLIO_ORDER, 1):
            observation = indexed.get((graph_number, method_id))
            if observation and observation.status == SOLVED:
                portfolio_stage = str(stage)
                portfolio_method = method_id
                portfolio_time = format_number(observation.time_sec)
                break

        timeout_class = data.baseline_timeout_class.get(graph_number, "")
        row: dict[str, Any] = {
            "graph_number": graph_number,
            "graph": f"graph{graph_number}",
            "vertices": features["vertices"],
            "undirected_edges": features["undirected_edges"],
            "m_over_n": format_number(features["m_over_n"]),
            "min_degree": features["min_degree"],
            "max_degree": features["max_degree"],
            "degree2_vertices": features["degree2_vertices"],
            "degree2_fraction": format_number(features["degree2_fraction"]),
            "hubs_degree_ge_50": features["hubs_degree_ge_50"],
            "structural_family": features["family"],
            "baseline_timeout_class": timeout_class,
            "known_solved_any": "TRUE" if solved_methods else "FALSE",
            "known_solved_method_count": len(solved_methods),
            "known_fastest_method_cross_source": all_fastest.method_id if all_fastest else "",
            "known_fastest_time_sec_cross_source": format_number(all_fastest.time_sec) if all_fastest else "",
            "paper_21_method_vbs_status": SOLVED if paper_fastest else TIMEOUT,
            "paper_21_method_vbs_best_method": paper_fastest.method_id if paper_fastest else "",
            "paper_21_method_vbs_best_time_sec": format_number(paper_fastest.time_sec) if paper_fastest else "",
            "four_stage_portfolio_status": SOLVED if portfolio_method else TIMEOUT,
            "four_stage_portfolio_stage": portfolio_stage,
            "four_stage_portfolio_method": portfolio_method,
            "four_stage_portfolio_time_sec": portfolio_time,
            "current_300_observed_method_count": len(current_observed),
            "current_300_solved_method_count": sum(item.status == SOLVED for item in current_observed),
            "current_300_fastest_method": current_fastest.method_id if current_fastest else "",
            "current_300_fastest_time_sec": format_number(current_fastest.time_sec) if current_fastest else "",
            "hcup_per_instance_evidence": (
                "LOCAL_RUN_SOLVED"
                if any(item.status == SOLVED for item in hcup_observed)
                else "LOCAL_RUN_OBSERVED_UNSOLVED"
                if hcup_observed
                else "AGGREGATE_ONLY_NO_LOCAL_LOGS"
            ),
            "recommended_next_action": (
                "already solved; route to the fastest verified local/published method"
                if solved_methods
                else open_instance_recommendation(timeout_class)
            ),
        }
        for method_id in per_instance_method_ids:
            observation = indexed.get((graph_number, method_id))
            row[f"status__{method_id}"] = observation.status if observation else MISSING
        rows.append(row)

    base_columns = list(rows[0].keys())[: -len(status_columns)]
    return rows, [*base_columns, *status_columns]


def build_method_summary_rows(
    data: CoverageData,
    indexed: dict[tuple[int, str], Observation],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for method_id, method in data.methods.items():
        records = [
            observation
            for (graph_number, current_method), observation in indexed.items()
            if current_method == method_id
        ]
        counts = Counter(item.status for item in records)
        solved_times = [
            item.time_sec
            for item in records
            if item.status == SOLVED and item.time_sec is not None
        ]
        solved_reported = (
            method.reported_solved
            if method.reported_solved is not None
            else counts[SOLVED]
        )
        rows.append(
            {
                "method_id": method_id,
                "display_name": method.display_name,
                "family": method.family,
                "per_instance_available": "TRUE" if method.per_instance_available else "FALSE",
                "timeout_sec": format_number(method.timeout_sec),
                "observed_per_instance": len(records),
                "missing_per_instance": DATASET_SIZE - len(records),
                "solved_per_instance": counts[SOLVED],
                "timeout_per_instance": counts[TIMEOUT],
                "incomplete_per_instance": counts[INCOMPLETE],
                "error_or_other_per_instance": len(records)
                - counts[SOLVED]
                - counts[TIMEOUT]
                - counts[INCOMPLETE],
                "reported_solved": solved_reported,
                "reported_timeout": (
                    method.reported_timeout
                    if method.reported_timeout is not None
                    else counts[TIMEOUT]
                    if method.per_instance_available
                    else ""
                ),
                "reported_oom": method.reported_oom if method.reported_oom is not None else "",
                "reported_abort": method.reported_abort if method.reported_abort is not None else "",
                "reported_coverage_pct": format_number(solved_reported / DATASET_SIZE),
                "min_solved_time_sec": format_number(min(solved_times)) if solved_times else "",
                "max_solved_time_sec": format_number(max(solved_times)) if solved_times else "",
                "source_path": method.source_path,
                "notes": method.notes,
            }
        )
    return rows


def build_portfolio_rows(
    data: CoverageData,
    indexed: dict[tuple[int, str], Observation],
) -> list[dict[str, Any]]:
    covered: set[int] = set()
    rows: list[dict[str, Any]] = []
    for stage, method_id in enumerate(PORTFOLIO_ORDER, 1):
        solved = {
            graph_number
            for graph_number in range(1, DATASET_SIZE + 1)
            if indexed.get((graph_number, method_id)) is not None
            and indexed[(graph_number, method_id)].status == SOLVED
        }
        new_graphs = sorted(solved - covered)
        covered.update(solved)
        rows.append(
            {
                "stage": stage,
                "method_id": method_id,
                "display_name": data.methods[method_id].display_name,
                "standalone_solved": len(solved),
                "new_solved_at_stage": len(new_graphs),
                "cumulative_solved": len(covered),
                "cumulative_coverage_pct": format_number(len(covered) / DATASET_SIZE),
                "new_graphs": " ".join(f"graph{number}" for number in new_graphs)
                if len(new_graphs) <= 30
                else "",
                "interpretation": "real configuration in a static fallback portfolio",
            }
        )
    open_graphs = sorted(set(range(1, DATASET_SIZE + 1)) - covered)
    rows.append(
        {
            "stage": "OPEN",
            "method_id": "",
            "display_name": "Unsolved by all 21 recorded paper/reference methods",
            "standalone_solved": "",
            "new_solved_at_stage": "",
            "cumulative_solved": len(covered),
            "cumulative_coverage_pct": format_number(len(covered) / DATASET_SIZE),
            "new_graphs": " ".join(f"graph{number}" for number in open_graphs),
            "interpretation": "research target; HCup per-instance results still missing",
        }
    )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if not rows and fieldnames is None:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = fieldnames or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_reports(data: CoverageData, output_dir: Path) -> dict[str, Path]:
    indexed = observation_index(data)
    instance_rows, instance_columns = build_instance_rows(data, indexed)
    method_rows = build_method_summary_rows(data, indexed)
    portfolio_rows = build_portfolio_rows(data, indexed)
    historical_open_rows = [
        row for row in instance_rows if row["paper_21_method_vbs_status"] == TIMEOUT
    ]
    current_open_rows = [row for row in instance_rows if row["known_solved_any"] == "FALSE"]

    observation_rows = []
    for item in sorted(
        data.observations,
        key=lambda current: (current.graph_number, current.method_id, current.time_sec or float("inf")),
    ):
        method = data.methods[item.method_id]
        observation_rows.append(
            {
                "graph_number": item.graph_number,
                "graph": f"graph{item.graph_number}",
                "method_id": item.method_id,
                "display_name": method.display_name,
                "family": method.family,
                "status": item.status,
                "time_sec": format_number(item.time_sec),
                "timeout_sec": format_number(item.timeout_sec),
                "verified": "" if item.verified is None else ("TRUE" if item.verified else "FALSE"),
                "source_path": item.source_path,
                "notes": item.notes,
            }
        )

    paths = {
        "instances": output_dir / "hybrid-instance-coverage.csv",
        "methods": output_dir / "hybrid-method-summary.csv",
        "portfolio": output_dir / "hybrid-portfolio-summary.csv",
        "historical_open": output_dir / "hybrid-historical-open-instances.csv",
        "open": output_dir / "hybrid-open-instances.csv",
        "observations": output_dir / "hybrid-run-observations.csv",
    }
    write_csv(paths["instances"], instance_rows, instance_columns)
    write_csv(paths["methods"], method_rows)
    write_csv(paths["portfolio"], portfolio_rows)
    write_csv(paths["historical_open"], historical_open_rows, instance_columns)
    write_csv(paths["open"], current_open_rows, instance_columns)
    write_csv(paths["observations"], observation_rows)
    return paths


def validate_reports(paths: dict[str, Path]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, path in paths.items():
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        counts[name] = len(rows)
        if not rows and name != "open":
            raise AssertionError(f"empty report: {path}")
    if counts["instances"] != DATASET_SIZE:
        raise AssertionError(f"instance report has {counts['instances']} rows")
    if counts["historical_open"] != 33:
        raise AssertionError(
            f"expected 33 historical open instances, got {counts['historical_open']}"
        )
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regression-console",
        type=Path,
        default=ROOT.parent / "regression-48h.console.log",
        help="Interrupted or completed hcp_benchmark console log.",
    )
    parser.add_argument(
        "--benchmark-results",
        type=Path,
        action="append",
        default=[],
        help="Optional results.jsonl from hcp_benchmark.py; may be repeated.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports/hybrid-coverage",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    regression_console = args.regression_console.resolve() if args.regression_console else None
    data = load_coverage_data(
        regression_console=regression_console,
        runner_jsonls=[path.resolve() for path in args.benchmark_results],
    )
    paths = write_reports(data, args.output_dir.resolve())
    counts = validate_reports(paths)
    indexed = observation_index(data)
    paper_union = {
        graph_number
        for graph_number in range(1, DATASET_SIZE + 1)
        if fastest_solved(graph_number, data.paper_method_ids, indexed) is not None
    }
    current_300_solved = {
        graph_number
        for (graph_number, method_id), observation in indexed.items()
        if data.methods[method_id].family == "current_regression_300s"
        and observation.status == SOLVED
    }
    minimum_portfolio, _ = minimum_portfolio_for_full_union(data.paper_method_ids, indexed)
    completed_regression = sum(
        1
        for item in data.observations
        if data.methods[item.method_id].family == "current_regression_300s"
        and item.status != INCOMPLETE
    )
    incomplete_regression = sum(
        1
        for item in data.observations
        if data.methods[item.method_id].family == "current_regression_300s"
        and item.status == INCOMPLETE
    )
    print(f"paper/reference VBS coverage: {len(paper_union)}/{DATASET_SIZE}")
    print(f"historical open instances: {DATASET_SIZE - len(paper_union)}")
    print(
        "minimum paper/reference configurations for that union: "
        f"{len(minimum_portfolio)} ({', '.join(minimum_portfolio)})"
    )
    print(f"current 300s solved graphs observed: {len(current_300_solved)}")
    print(
        f"regression console: {completed_regression} completed, "
        f"{incomplete_regression} incomplete"
    )
    for name, path in paths.items():
        print(f"{name}: {path} ({counts[name]} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
