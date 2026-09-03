#!/usr/bin/env python3
"""AHS v1: a verified, budgeted portfolio for Hamiltonian-cycle SAT solvers.

This is deliberately a fixed-rule controller, not a learned selector and not a
new claim that the backends share SAT state. It selects an explicit route from
graph features, gives each backend a cumulative deadline, and accepts SAT only
after independent tour verification.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import hcp_benchmark as runner


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "benchmarks" / "ahs_policy.json"
CONTROLLED_ENV = {
    "RAYON_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "RUST_TEST_THREADS": "1",
}


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("AHS config schema_version must be 1")

    controller = config.get("controller")
    if not isinstance(controller, dict):
        raise ValueError("AHS config must declare its controller")
    if controller.get("type") != "fixed_rules":
        raise ValueError("this AHS implementation supports only a fixed_rules controller")
    if controller.get("uses_machine_learning") is not False:
        raise ValueError("AHS v1 must explicitly disable machine learning")

    raw_backends = config.get("backends")
    if not isinstance(raw_backends, list) or not raw_backends:
        raise ValueError("AHS config must contain a non-empty backends list")
    names = [backend.get("name") for backend in raw_backends]
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("every AHS backend needs a non-empty name")
    if len(names) != len(set(names)):
        raise ValueError("AHS backend names must be unique")
    for backend in raw_backends:
        for key in ("source_dir", "binary"):
            if not isinstance(backend.get(key), str) or not backend[key]:
                raise ValueError(f"backend {backend['name']!r} needs {key}")

    policies = config.get("policies")
    if not isinstance(policies, dict) or not policies:
        raise ValueError("AHS config must contain policies")
    default_policy = config.get("default_policy")
    if default_policy not in policies:
        raise ValueError("default_policy does not name a configured policy")
    routing = config.get("routing")
    if not isinstance(routing, dict):
        raise ValueError("AHS config must contain routing thresholds")
    for key in ("dense_m_over_n_min", "degree2_fraction_min_exclusive"):
        value = routing.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise ValueError(f"routing threshold {key!r} must be non-negative")

    known_backends = set(names)
    for policy_name, policy in policies.items():
        routes = policy.get("routes") if isinstance(policy, dict) else None
        if not isinstance(routes, dict) or not routes:
            raise ValueError(f"policy {policy_name!r} must contain routes")
        missing_families = {"dense", "sparse_degree2", "sparse_other"} - set(routes)
        if missing_families:
            raise ValueError(
                f"policy {policy_name!r} is missing routes: {sorted(missing_families)}"
            )
        for family, stages in routes.items():
            if not isinstance(stages, list) or not stages:
                raise ValueError(f"route {policy_name}/{family} must not be empty")
            total = 0.0
            for stage in stages:
                backend_name = stage.get("backend") if isinstance(stage, dict) else None
                if backend_name not in known_backends:
                    raise ValueError(
                        f"route {policy_name}/{family} uses unknown backend {backend_name!r}"
                    )
                fraction = stage.get("fraction")
                if (
                    isinstance(fraction, bool)
                    or not isinstance(fraction, (int, float))
                    or not math.isfinite(float(fraction))
                    or fraction <= 0
                ):
                    raise ValueError(
                        f"route {policy_name}/{family} has an invalid fraction; "
                        "it must be a finite positive number"
                    )
                total += float(fraction)
            if abs(total - 1.0) > 1e-9:
                raise ValueError(
                    f"route {policy_name}/{family} fractions sum to {total}, not 1"
                )


def backend_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {backend["name"]: backend for backend in config["backends"]}


def classify_route(
    features: dict[str, Any], routing: dict[str, Any] | None = None
) -> str:
    """Use only reproducible graph features; never use an instance-ID oracle."""
    routing = routing or {
        "dense_m_over_n_min": 3.0,
        "degree2_fraction_min_exclusive": 0.10,
    }
    ratio = float(features.get("m_over_n") or 0.0)
    degree2_fraction = float(features.get("degree2_fraction") or 0.0)
    if ratio >= float(routing["dense_m_over_n_min"]):
        return "dense"
    if degree2_fraction > float(routing["degree2_fraction_min_exclusive"]):
        return "sparse_degree2"
    return "sparse_other"


def cumulative_stage_fractions(stages: list[dict[str, Any]]) -> list[float]:
    cumulative: list[float] = []
    total = 0.0
    for stage in stages:
        total += float(stage["fraction"])
        cumulative.append(total)
    return cumulative


def policy_backend_names(config: dict[str, Any], policy_name: str) -> list[str]:
    names: list[str] = []
    for stages in config["policies"][policy_name]["routes"].values():
        for stage in stages:
            name = stage["backend"]
            if name not in names:
                names.append(name)
    return names


def expected_binary(backend: dict[str, Any]) -> Path:
    return (ROOT / backend["binary"]).resolve()


def prepare_backends(
    config: dict[str, Any],
    policy_name: str,
    env: dict[str, str],
    build_dir: Path,
    no_build: bool,
    rebuild: bool,
) -> dict[str, Path]:
    indexed = backend_index(config)
    binaries: dict[str, Path] = {}
    rebuilt_paths: set[Path] = set()
    for name in policy_backend_names(config, policy_name):
        backend = indexed[name]
        binary = expected_binary(backend)
        should_build = (rebuild and binary not in rebuilt_paths) or (
            not no_build and not binary.is_file()
        )
        if should_build:
            build_system = backend.get("build_system", "cargo")
            tool = "cargo" if build_system == "cargo" else "cmake" if build_system == "cmake" else None
            if tool and shutil.which(tool) is None:
                raise RuntimeError(f"{tool} not found; cannot build backend {name}")
            binary = runner.build_variant(backend, env, build_dir)
            rebuilt_paths.add(binary.resolve())
        if not binary.is_file():
            hint = "run without --no-build first" if no_build else "check the backend configuration"
            raise FileNotFoundError(f"backend {name} not found: {binary}; {hint}")
        if not backend.get("interpreter") and not os.access(binary, os.X_OK):
            raise PermissionError(f"backend {name} is not executable: {binary}")
        binaries[name] = binary
    return binaries


def write_tour(path: Path, tour: list[int], graph_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(str(vertex) for vertex in tour)
    path.write_text(
        f"NAME : {graph_name}-ahs-tour\n"
        "COMMENT : Independently verified by AHS\n"
        "TYPE : TOUR\n"
        f"DIMENSION : {len(tour)}\n"
        "TOUR_SECTION\n"
        f"{body}\n"
        "-1\n"
        "EOF\n",
        encoding="utf-8",
    )


def raw_log_text(
    command: list[str],
    returncode: int | None,
    timed_out: bool,
    wall_sec: float,
    stdout: str,
    stderr: str,
) -> str:
    return (
        f"COMMAND: {json.dumps(command, ensure_ascii=False)}\n"
        f"RETURNCODE: {returncode}\n"
        f"TIMED_OUT: {timed_out}\n"
        f"WALL_SEC: {wall_sec:.9f}\n"
        "\n===== STDOUT =====\n"
        f"{stdout}"
        "\n===== STDERR =====\n"
        f"{stderr}"
    )


def run_stage(
    backend: dict[str, Any],
    binary: Path,
    graph_path: Path,
    timeout_sec: float,
    vertices: set[int],
    edges: set[tuple[int, int]],
    raw_path: Path,
    env: dict[str, str],
) -> tuple[dict[str, Any], list[int] | None]:
    backend_tour = raw_path.with_suffix(".tour")
    command = [
        *runner.variant_command_prefix(backend, binary),
        *runner.variant_input_argv(backend, graph_path),
        *runner.option_argv(backend.get("options", {})),
        *[str(value) for value in backend.get("arguments", [])],
    ]
    if backend.get("supports_internal_timeout", False):
        command.extend(["--timeout", str(timeout_sec)])
    if backend.get("supports_output_tour", False):
        command.extend(["--output-tour", str(backend_tour)])

    try:
        returncode, stdout, stderr, timed_out, wall_sec = runner.run_process(
            command, timeout_sec, env
        )
        parsed_status = (
            "TIMEOUT"
            if timed_out
            else runner.parse_status(stdout, str(backend.get("status_protocol", "dimacs")))
        )
        tour = runner.parse_tour_file(backend_tour) or runner.parse_tour_stdout(stdout)
        verified, verification_reason = runner.verify_tour(tour, vertices, edges)
        status = parsed_status
        if parsed_status == "SATISFIABLE" and not verified:
            status = "INVALID_SAT"
        elif parsed_status == "UNSATISFIABLE" and not backend.get("trust_unsat", False):
            status = "UNTRUSTED_UNSAT"
        elif parsed_status == "NO_STATUS" and returncode not in (0, 10, 20):
            status = "ERROR"
        elif parsed_status in ("NO_STATUS", "ERROR"):
            status = "UNKNOWN" if parsed_status == "NO_STATUS" else "ERROR"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(
            raw_log_text(command, returncode, timed_out, wall_sec, stdout, stderr),
            encoding="utf-8",
        )
        result = {
            "backend": backend["name"],
            "command": command,
            "allocated_timeout_sec": timeout_sec,
            "status": status,
            "solver_status": parsed_status,
            "returncode": returncode,
            "timed_out": timed_out,
            "wall_sec": wall_sec,
            "verified": verified,
            "verification_reason": verification_reason,
            "tour_vertices": len(tour) if tour else None,
            "raw_log": str(raw_path),
        }
        phase_stats, phase_seconds = runner.parse_metrics(stdout)
        increment_matches = runner.INCREMENT_RE.findall(stdout)
        clause_matches = runner.CLAUSE_RE.findall(stdout)
        result.update(
            {
                "increments": int(increment_matches[-1]) if increment_matches else None,
                "blocking_clauses": int(clause_matches[-1]) if clause_matches else None,
                "phase_stats": phase_stats,
                "phase_seconds": phase_seconds,
                "solver_stats": runner.parse_solver_stats(stdout),
                "backend_result": runner.parse_backend_result(stdout),
                "backend_activity": runner.parse_hcup_activity(stdout),
            }
        )
        return result, tour
    except OSError as error:
        wall_sec = 0.0
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(
            raw_log_text(command, None, False, wall_sec, "", f"{type(error).__name__}: {error}\n"),
            encoding="utf-8",
        )
        return (
            {
                "backend": backend["name"],
                "command": command,
                "allocated_timeout_sec": timeout_sec,
                "status": "ERROR",
                "solver_status": "NO_STATUS",
                "returncode": None,
                "timed_out": False,
                "wall_sec": wall_sec,
                "verified": False,
                "verification_reason": "process_start_failed",
                "tour_vertices": None,
                "raw_log": str(raw_path),
                "error": f"{type(error).__name__}: {error}",
            },
            None,
        )


def exhausted_status(stage_results: list[dict[str, Any]]) -> str:
    hard_failures = {"ERROR", "INVALID_SAT", "UNTRUSTED_UNSAT"}
    return "ERROR" if any(result["status"] in hard_failures for result in stage_results) else "UNKNOWN"


def transition_reason(stage_results: list[dict[str, Any]]) -> str:
    """Explain a policy transition without consulting an instance-ID oracle."""
    if not stage_results:
        return "policy_route_start"
    status = str(stage_results[-1].get("status", "UNKNOWN")).lower()
    return f"previous_stage_{status}"


def make_run_dir(graph_path: Path | None, requested: Path | None) -> Path:
    if requested is not None:
        run_dir = requested.resolve()
    else:
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        graph_name = runner.safe_name(graph_path.stem if graph_path else "build")
        run_dir = ROOT / "ahs-runs" / f"{timestamp}-{graph_name}-{os.getpid()}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("-i", "--input", type=Path, help="HCP graph in .col format")
    argument_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    argument_parser.add_argument("--policy", help="Policy name; default comes from the config")
    argument_parser.add_argument(
        "--timeout", "--budget", dest="budget", type=float, default=1800.0,
        help="Total solving budget in seconds; backend build time is excluded",
    )
    argument_parser.add_argument(
        "--shutdown-reserve", type=float, default=2.0,
        help="Budget reserved for process termination, verification, and artifact writing",
    )
    argument_parser.add_argument("--output-tour", type=Path)
    argument_parser.add_argument("--run-dir", type=Path)
    argument_parser.add_argument("--no-build", action="store_true")
    argument_parser.add_argument("--rebuild", action="store_true")
    argument_parser.add_argument("--build-only", action="store_true")
    argument_parser.add_argument("--dry-run", action="store_true")
    return argument_parser


def main() -> int:
    args = parser().parse_args()
    config_path = args.config.resolve()
    config = load_config(config_path)
    policy_name = args.policy or config["default_policy"]
    if policy_name not in config["policies"]:
        raise KeyError(f"unknown AHS policy: {policy_name}")
    if args.no_build and args.rebuild:
        raise ValueError("--no-build and --rebuild cannot be used together")
    if args.build_only and args.dry_run:
        raise ValueError("--build-only and --dry-run cannot be used together")
    if not args.build_only and args.input is None:
        raise ValueError("--input is required unless --build-only is used")
    if args.budget <= 0:
        raise ValueError("--timeout/--budget must be positive")
    if args.shutdown_reserve < 0 or args.shutdown_reserve >= args.budget:
        raise ValueError("--shutdown-reserve must be non-negative and smaller than the budget")

    graph_path = args.input.resolve() if args.input else None
    if graph_path is not None and not graph_path.is_file():
        raise FileNotFoundError(graph_path)
    if args.dry_run:
        assert graph_path is not None
        features, _, _ = runner.graph_features(graph_path)
        family = classify_route(features, config["routing"])
        stages = config["policies"][policy_name]["routes"][family]
        cumulative = cumulative_stage_fractions(stages)
        print(
            f"c ahs implementation=AHS-v1-driver controller=fixed_rules "
            f"machine_learning=false policy={policy_name} route={family} "
            f"budget_sec={args.budget:g}"
        )
        for index, stage in enumerate(stages, 1):
            print(
                f"c ahs_stage_plan index={index} backend={stage['backend']} "
                f"fraction={float(stage['fraction']):.6f} cumulative={cumulative[index - 1]:.6f}"
            )
        print("c ahs_dry_run_complete")
        return 0

    run_dir = make_run_dir(graph_path, args.run_dir)
    env = os.environ.copy()
    env.update(CONTROLLED_ENV)
    binaries = prepare_backends(
        config,
        policy_name,
        env,
        run_dir / "build",
        no_build=args.no_build,
        rebuild=args.rebuild,
    )
    if args.build_only:
        print("c ahs_build_complete " + " ".join(f"{name}={path}" for name, path in binaries.items()))
        return 0

    assert graph_path is not None
    budget_started = time.perf_counter()
    features, vertices, edges = runner.graph_features(graph_path)
    family = classify_route(features, config["routing"])
    policy = config["policies"][policy_name]
    stages = policy["routes"][family]
    indexed = backend_index(config)
    cumulative = cumulative_stage_fractions(stages)
    usable_budget = args.budget - args.shutdown_reserve
    output_tour = (args.output_tour or run_dir / "solution.tour").resolve()

    manifest = {
        "schema_version": 1,
        "created_utc": runner.utc_now(),
        "implementation": "AHS-v1-driver",
        "controller": str(Path(__file__).resolve()),
        "controller_mode": config["controller"],
        "controller_sha256": runner.sha256_file(Path(__file__).resolve()),
        "config": str(config_path),
        "config_sha256": runner.sha256_file(config_path),
        "command": sys.argv,
        "graph": str(graph_path),
        "graph_sha256": runner.sha256_file(graph_path),
        "graph_features": features,
        "policy": policy_name,
        "route": family,
        "routing": config["routing"],
        "stages": stages,
        "budget_sec": args.budget,
        "usable_controller_and_backend_budget_sec": usable_budget,
        "shutdown_reserve_sec": args.shutdown_reserve,
        "controlled_environment": CONTROLLED_ENV,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version,
        },
        "binaries": {
            name: {"path": str(path), "sha256": runner.sha256_file(path)}
            for name, path in binaries.items()
        },
        "sources": {
            str((ROOT / indexed[name]["source_dir"]).resolve()): runner.git_metadata(
                (ROOT / indexed[name]["source_dir"]).resolve()
            )
            for name in binaries
        },
        "disabled_components": config.get("disabled_components", []),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(
        f"c ahs implementation=AHS-v1-driver controller=fixed_rules "
        f"machine_learning=false policy={policy_name} route={family} "
        f"budget_sec={args.budget:g}"
    )
    stage_results: list[dict[str, Any]] = []
    final_status: str | None = None
    final_tour: list[int] | None = None
    winning_backend: str | None = None

    for index, (stage, cumulative_fraction) in enumerate(zip(stages, cumulative), 1):
        reason = transition_reason(stage_results)
        stage_deadline = budget_started + usable_budget * cumulative_fraction
        available = stage_deadline - time.perf_counter()
        if available <= 0:
            result = {
                "backend": stage["backend"],
                "allocated_timeout_sec": 0.0,
                "status": "SKIPPED_NO_BUDGET",
                "solver_status": "NO_STATUS",
                "timed_out": False,
                "wall_sec": 0.0,
                "verified": False,
                "verification_reason": "cumulative_deadline_elapsed",
                "transition_reason": reason,
            }
            stage_results.append(result)
            print(
                f"c ahs_stage_end index={index} backend={stage['backend']} "
                "status=SKIPPED_NO_BUDGET wall_sec=0"
            )
            continue

        backend = indexed[stage["backend"]]
        print(
            f"c ahs_stage_start index={index} backend={backend['name']} "
            f"timeout_sec={available:.6f} cumulative_fraction={cumulative_fraction:.6f} "
            f"reason={reason}"
        )
        result, tour = run_stage(
            backend,
            binaries[backend["name"]],
            graph_path,
            available,
            vertices,
            edges,
            run_dir / "raw" / f"stage-{index:02d}-{runner.safe_name(backend['name'])}.txt",
            env,
        )
        result["stage_index"] = index
        result["fraction"] = float(stage["fraction"])
        result["cumulative_fraction"] = cumulative_fraction
        result["deadline_from_budget_start_sec"] = usable_budget * cumulative_fraction
        result["transition_reason"] = reason
        stage_results.append(result)
        print(
            f"c ahs_stage_end index={index} backend={backend['name']} "
            f"status={result['status']} wall_sec={result['wall_sec']:.6f} "
            f"verified={str(result['verified']).lower()}"
        )

        if result["status"] == "SATISFIABLE" and result["verified"]:
            final_status = "SATISFIABLE"
            final_tour = tour
            winning_backend = backend["name"]
            break
        if result["status"] == "UNSATISFIABLE":
            final_status = "UNSATISFIABLE"
            winning_backend = backend["name"]
            break

    route_exhausted = final_status is None
    if final_status is None:
        final_status = exhausted_status(stage_results)

    if final_status == "SATISFIABLE":
        assert final_tour is not None
        write_tour(output_tour, final_tour, graph_path.stem)
    total_wall_sec = time.perf_counter() - budget_started
    last_stage = stage_results[-1] if stage_results else {}
    budget_exhausted = route_exhausted and (
        bool(last_stage.get("timed_out"))
        or last_stage.get("status") == "SKIPPED_NO_BUDGET"
        or total_wall_sec >= usable_budget - 0.05
    )
    summary = {
        "schema_version": 1,
        "finished_utc": runner.utc_now(),
        "status": final_status,
        "verified": final_status == "SATISFIABLE",
        "winning_backend": winning_backend,
        "tour_path": str(output_tour) if final_status == "SATISFIABLE" else None,
        "tour_vertices": len(final_tour) if final_tour else None,
        "wall_sec": total_wall_sec,
        "budget_sec": args.budget,
        "within_total_budget": total_wall_sec <= args.budget,
        "budget_overrun_sec": max(0.0, total_wall_sec - args.budget),
        "budget_exhausted": budget_exhausted,
        "route_exhausted": route_exhausted,
        "policy": policy_name,
        "route": family,
        "controller_mode": config["controller"],
        "stage_results": stage_results,
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"c ahs_summary={run_dir / 'summary.json'}")
    print(
        "c result_json="
        + json.dumps(
            {
                "implementation": "AHS-v1-driver",
                "policy": policy_name,
                "route": family,
                "budget_exhausted": budget_exhausted,
                "route_exhausted": route_exhausted,
                "winning_backend": winning_backend,
                "stage_outcomes": [
                    {
                        "backend": result["backend"],
                        "status": result["status"],
                        "wall_sec": result["wall_sec"],
                    }
                    for result in stage_results
                ],
            },
            separators=(",", ":"),
        )
    )
    if final_status == "SATISFIABLE":
        print("solution:")
        print(" ".join(str(vertex) for vertex in final_tour or []))
        print("s SATISFIABLE")
        return 10
    if final_status == "UNSATISFIABLE":
        print("s UNSATISFIABLE")
        return 20
    if final_status == "ERROR":
        print("s ERROR")
        return 1
    print("s UNKNOWN")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("s UNKNOWN")
        raise SystemExit(130)
    except Exception as error:  # Keep the command-line protocol explicit on setup failures.
        print(f"c ahs_error={type(error).__name__}: {error}", file=sys.stderr)
        print("s ERROR")
        raise SystemExit(1)
