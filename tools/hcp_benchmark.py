#!/usr/bin/env python3
"""Reproducible, dependency-free benchmark runner for the FHCP solvers."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
STATUS_RE = re.compile(r"^s (SATISFIABLE|UNSATISFIABLE|UNKNOWN|ERROR)(?:\s|$)")
INTEGER_LINE_RE = re.compile(r"^\s*\d+(?:\s+\d+)+\s*$")
METRIC_RE = re.compile(r"^c metric (?P<body>.*)$")
INCREMENT_RE = re.compile(r"overall incremented number\s*=\s*(\d+)")
CLAUSE_RE = re.compile(r"overall number of added block clauses\s*=\s*(\d+)")
SOLVER_STATS_RE = re.compile(r"^c solver_stats (?P<body>.*)$")
BACKEND_RESULT_PREFIX = "c result_json="


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cargo_lock_versions(path: Path, package_names: Iterable[str]) -> dict[str, str]:
    if not path.is_file():
        return {}
    wanted = set(package_names)
    versions: dict[str, str] = {}
    current_name: str | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        name_match = re.fullmatch(r'name = "([^"]+)"', line)
        if name_match:
            current_name = name_match.group(1)
            continue
        version_match = re.fullmatch(r'version = "([^"]+)"', line)
        if version_match and current_name in wanted:
            versions[current_name] = version_match.group(1)
    return versions


def command_version(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0] if text else None


def git_metadata(path: Path) -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(path), *args],
                text=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {
        "path": str(path),
        "commit": commit,
        "dirty": bool(status) if status is not None else None,
        "status_porcelain": status,
    }


def parse_instance_spec(spec: str) -> list[int]:
    values: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-")
            if len(parts) not in (2, 3):
                raise ValueError(f"invalid range: {token}")
            start, end = int(parts[0]), int(parts[1])
            step = int(parts[2]) if len(parts) == 3 else 1
            if step <= 0 or end < start:
                raise ValueError(f"invalid range: {token}")
            values.update(range(start, end + 1, step))
        else:
            values.add(int(token))
    return sorted(values)


def load_instance_set(path: Path, name: str) -> list[int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if name not in payload["sets"]:
        raise KeyError(f"instance set {name!r} not found in {path}")
    value = payload["sets"][name]
    if isinstance(value, list):
        return sorted({int(item) for item in value})
    if isinstance(value, str):
        return parse_instance_spec(value)
    raise TypeError(f"instance set {name!r} must be a list or range string")


def deep_merge(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    merged = dict(parent)
    for key, value in child.items():
        if key == "options":
            merged[key] = {**parent.get(key, {}), **value}
        elif key != "extends":
            merged[key] = value
    return merged


def resolve_variants(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = {variant["name"]: variant for variant in config["variants"]}
    resolved: dict[str, dict[str, Any]] = {}

    def resolve(name: str, stack: tuple[str, ...] = ()) -> dict[str, Any]:
        if name in resolved:
            return resolved[name]
        if name in stack:
            raise ValueError(f"variant inheritance cycle: {' -> '.join((*stack, name))}")
        variant = raw[name]
        if "extends" in variant:
            parent = resolve(variant["extends"], (*stack, name))
            result = deep_merge(parent, variant)
        else:
            result = dict(variant)
        result["name"] = name
        resolved[name] = result
        return result

    for variant_name in raw:
        resolve(variant_name)
    return resolved


def option_argv(options: dict[str, Any]) -> list[str]:
    argv: list[str] = []
    for flag, value in options.items():
        if value is None or value is False:
            continue
        argv.append(flag)
        if value is not True:
            argv.append(str(value))
    return argv


def variant_command_prefix(variant: dict[str, Any], binary: Path) -> list[str]:
    """Return an optional interpreter followed by the configured program."""
    interpreter = variant.get("interpreter")
    return [str(interpreter), str(binary)] if interpreter else [str(binary)]


def variant_input_argv(variant: dict[str, Any], graph_path: Path) -> list[str]:
    """Support both `-i graph` and positional graph command-line protocols."""
    input_flag = variant.get("input_flag", "-i")
    if input_flag is None:
        return [str(graph_path)]
    return [str(input_flag), str(graph_path)]


def graph_features(path: Path) -> tuple[dict[str, Any], set[int], set[tuple[int, int]]]:
    declared_n = None
    vertices: set[int] = set()
    edges: set[tuple[int, int]] = set()
    degree: Counter[int] = Counter()
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "p" and len(parts) >= 3:
                declared_n = int(parts[1])
            elif parts[0] == "e" and len(parts) >= 3:
                u, v = int(parts[1]), int(parts[2])
                if u == v:
                    continue
                edge = (u, v) if u < v else (v, u)
                if edge not in edges:
                    edges.add(edge)
                    vertices.update(edge)
                    degree[u] += 1
                    degree[v] += 1
    n = declared_n or len(vertices)
    if declared_n:
        vertices.update(range(1, declared_n + 1))
    degrees = [degree[v] for v in vertices]
    degree2 = sum(value == 2 for value in degrees)
    hubs50 = sum(value >= 50 for value in degrees)
    density_m_over_n = len(edges) / n if n else math.nan
    family = (
        "dense"
        if density_m_over_n >= 3.0
        else "sparse_degree2"
        if n and degree2 / n > 0.10
        else "sparse_other"
    )
    return (
        {
            "vertices": n,
            "undirected_edges": len(edges),
            "m_over_n": density_m_over_n,
            "min_degree": min(degrees) if degrees else None,
            "max_degree": max(degrees) if degrees else None,
            "degree2_vertices": degree2,
            "degree2_fraction": degree2 / n if n else None,
            "hubs_degree_ge_50": hubs50,
            "family": family,
        },
        vertices,
        edges,
    )


def parse_tour_file(path: Path) -> list[int] | None:
    if not path.is_file():
        return None
    values: list[int] = []
    in_section = False
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line == "TOUR_SECTION":
            in_section = True
            continue
        if not in_section:
            continue
        if line in ("-1", "EOF"):
            break
        if re.fullmatch(r"-?\d+", line):
            values.append(int(line))
    return values or None


def parse_tour_stdout(stdout: str) -> list[int] | None:
    lines = stdout.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        marker = lines[index].strip().lower()
        if marker.startswith("solution:") or marker.startswith("model:"):
            suffix = lines[index].split(":", 1)[1].strip()
            if suffix and INTEGER_LINE_RE.fullmatch(suffix):
                return [int(value) for value in suffix.split()]
            for candidate in lines[index + 1 : index + 4]:
                if INTEGER_LINE_RE.fullmatch(candidate):
                    return [int(value) for value in candidate.split()]
    return None


def verify_tour(
    tour: list[int] | None,
    vertices: set[int],
    edges: set[tuple[int, int]],
) -> tuple[bool, str]:
    if tour is None:
        return False, "tour_missing"
    if len(tour) != len(vertices):
        return False, f"wrong_length:{len(tour)}!={len(vertices)}"
    if set(tour) != vertices:
        return False, "vertex_set_mismatch"
    for index, u in enumerate(tour):
        v = tour[(index + 1) % len(tour)]
        edge = (u, v) if u < v else (v, u)
        if edge not in edges:
            return False, f"missing_edge:{u}-{v}"
    return True, "verified"


def parse_status(stdout: str, protocol: str = "dimacs") -> str:
    if protocol == "hcup":
        statuses = []
        for line in stdout.splitlines():
            value = line.strip()
            if value == "SAT":
                statuses.append("SATISFIABLE")
            elif value.startswith("UNSAT"):
                statuses.append("UNSATISFIABLE")
            elif value == "INTERRUPTED" or value.startswith("Interrupt signal"):
                statuses.append("UNKNOWN")
        return statuses[-1] if statuses else "NO_STATUS"
    if protocol != "dimacs":
        raise ValueError(f"unknown status protocol: {protocol}")
    statuses = []
    for line in stdout.splitlines():
        match = STATUS_RE.match(line.strip())
        if match:
            statuses.append(match.group(1))
    return statuses[-1] if statuses else "NO_STATUS"


def parse_metrics(stdout: str) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    phase_stats: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "seconds": 0.0,
            "cycles_before_total": 0,
            "cycles_after_total": 0,
            "cycle_reduction_total": 0,
            "improving_calls": 0,
        }
    )
    phase_seconds: defaultdict[str, float] = defaultdict(float)
    for line in stdout.splitlines():
        match = METRIC_RE.match(line.strip())
        if not match:
            continue
        metric: dict[str, Any] = {}
        for field in match.group("body").split():
            key, separator, value = field.partition("=")
            if not separator:
                continue
            if key in {"iteration", "cycles_before", "cycles_after"}:
                metric[key] = int(value)
            elif key == "seconds":
                metric[key] = float(value)
            else:
                metric[key] = value
        if metric and "phase" in metric:
            phase = str(metric["phase"])
            seconds = float(metric.get("seconds", 0.0))
            before = int(metric.get("cycles_before", 0))
            after = int(metric.get("cycles_after", before))
            stats = phase_stats[phase]
            stats["calls"] += 1
            stats["seconds"] += seconds
            stats["cycles_before_total"] += before
            stats["cycles_after_total"] += after
            stats["cycle_reduction_total"] += before - after
            stats["improving_calls"] += after < before
            phase_seconds[phase] += seconds
    return dict(phase_stats), dict(phase_seconds)


def parse_solver_stats(stdout: str) -> dict[str, Any] | None:
    last: dict[str, Any] | None = None
    integer_fields = {
        "iteration",
        "conflicts",
        "decisions",
        "propagations",
        "clauses",
        "variables",
    }
    float_fields = {"avg_clause_len", "cpu_solve_seconds"}
    for line in stdout.splitlines():
        match = SOLVER_STATS_RE.match(line.strip())
        if not match:
            continue
        values: dict[str, Any] = {}
        for field in match.group("body").split():
            key, separator, value = field.partition("=")
            if not separator:
                continue
            if key in integer_fields:
                values[key] = int(value)
            elif key in float_fields:
                values[key] = float(value)
            else:
                values[key] = value
        last = values
    return last


def parse_backend_result(stdout: str) -> dict[str, Any] | None:
    """Parse an optional backend-owned JSON summary without trusting its certificate."""
    last: dict[str, Any] | None = None
    for line in stdout.splitlines():
        value = line.strip()
        if not value.startswith(BACKEND_RESULT_PREFIX):
            continue
        try:
            payload = json.loads(value[len(BACKEND_RESULT_PREFIX) :])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            last = payload
    return last


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass


def run_process(command: list[str], timeout_sec: float, env: dict[str, str]) -> tuple[int | None, str, str, bool, float]:
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=(os.name == "posix"),
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_process(process)
        stdout, stderr = process.communicate()
    except KeyboardInterrupt:
        terminate_process(process)
        process.communicate()
        raise
    return process.returncode, stdout, stderr, timed_out, time.perf_counter() - started


def build_variant(
    variant: dict[str, Any], env: dict[str, str], output_dir: Path
) -> Path:
    for prerequisite in variant.get("build_prerequisites", []):
        build_variant(prerequisite, env, output_dir)
    source_dir = (ROOT / variant["source_dir"]).resolve()
    build_system = variant.get("build_system", "cargo")
    if variant.get("isolated_build", False):
        if build_system != "cargo":
            raise ValueError("isolated_build is currently supported only for Cargo variants")
        isolated_source = output_dir / "build-sources" / safe_name(variant["name"])
        if isolated_source.exists():
            shutil.rmtree(isolated_source)
        shutil.copytree(
            source_dir,
            isolated_source,
            ignore=shutil.ignore_patterns("target", ".git", "*.log", "*.cnf"),
        )
        source_dir = isolated_source
    if build_system == "cargo":
        command = ["cargo", "build", "--release", *variant.get("build_args", [])]
        print(f"[build] {variant['name']}: {' '.join(command)} ({source_dir})", flush=True)
        result = subprocess.run(command, cwd=source_dir, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"build failed for variant {variant['name']}")
        binary_name = Path(variant["binary"]).name
        return source_dir / "target" / "release" / binary_name
    if build_system == "cmake":
        build_dir = source_dir / variant.get("cmake_build_dir", "cmake-build-release")
        configure = [
            "cmake",
            "-S",
            str(source_dir),
            "-B",
            str(build_dir),
            "-DCMAKE_BUILD_TYPE=Release",
            *variant.get("configure_args", []),
        ]
        build = [
            "cmake",
            "--build",
            str(build_dir),
            "--target",
            variant.get("cmake_target", Path(variant["binary"]).name),
            "-j",
            str(variant.get("build_jobs", os.cpu_count() or 2)),
            *variant.get("build_args", []),
        ]
        for command in (configure, build):
            print(f"[build] {variant['name']}: {' '.join(command)}", flush=True)
            result = subprocess.run(command, cwd=source_dir, env=env)
            if result.returncode != 0:
                raise RuntimeError(f"build failed for variant {variant['name']}")
        return build_dir / Path(variant["binary"]).name
    if build_system == "none":
        return (ROOT / variant["binary"]).resolve()
    raise ValueError(f"unknown build_system {build_system!r} for {variant['name']}")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def load_completed(
    path: Path,
) -> tuple[set[tuple[str, int, int]], set[tuple[int, int]]]:
    completed: set[tuple[str, int, int]] = set()
    solved: set[tuple[int, int]] = set()
    if not path.is_file():
        return completed, solved
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
            graph_number = int(row["graph_number"])
            repetition = int(row.get("repetition", 1))
            completed.add((row["variant"], graph_number, repetition))
            if row.get("status") == "SATISFIABLE" and row.get("verified") is True:
                solved.add((graph_number, repetition))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return completed, solved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "benchmarks/ablation_variants.json")
    parser.add_argument("--instance-sets", type=Path, default=ROOT / "benchmarks/instance_sets.json")
    parser.add_argument("--set", dest="set_name", default="regression_core")
    parser.add_argument("--instances", help="Override set, e.g. 1-1001 or 339,479,797")
    parser.add_argument("--variants", help="Comma-separated variant names; default is config default_variants")
    parser.add_argument("--timeout", type=float, help="Strict external timeout per instance")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--stop-on-solved",
        action="store_true",
        help="Treat selected variants as an ordered portfolio and skip later variants after a verified solution.",
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--random-seed", type=int, default=20260824)
    args = parser.parse_args()
    if args.stop_on_solved and args.shuffle:
        raise ValueError("--stop-on-solved requires deterministic variant order; do not use --shuffle")

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    variants = resolve_variants(config)
    selected_names = (
        [name.strip() for name in args.variants.split(",") if name.strip()]
        if args.variants
        else config["default_variants"]
    )
    missing = [name for name in selected_names if name not in variants]
    if missing:
        raise KeyError(f"unknown variants: {', '.join(missing)}")
    selected = [variants[name] for name in selected_names]

    graph_numbers = (
        parse_instance_spec(args.instances)
        if args.instances
        else load_instance_set(args.instance_sets.resolve(), args.set_name)
    )
    timeout_sec = args.timeout or float(config.get("timeout_sec", 1800))
    if timeout_sec <= 0 or args.repetitions <= 0:
        raise ValueError("timeout and repetitions must be positive")

    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = (args.output or ROOT / "benchmark-runs" / run_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=args.resume)
    raw_dir = output_dir / "raw"
    tour_dir = output_dir / "tours"
    raw_dir.mkdir(parents=True, exist_ok=True)
    tour_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.jsonl"

    env = os.environ.copy()
    controlled_env = {
        "RAYON_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "RUST_TEST_THREADS": "1",
    }
    env.update(controlled_env)

    actual_binaries: dict[str, Path] = {}
    if not args.no_build:
        build_systems = {variant.get("build_system", "cargo") for variant in selected}
        if "cargo" in build_systems and shutil.which("cargo") is None:
            raise RuntimeError("cargo not found; install Rust or use --no-build with prebuilt binaries")
        if "cmake" in build_systems and shutil.which("cmake") is None:
            raise RuntimeError("cmake not found; install CMake or use --no-build with prebuilt binaries")
        built_sources: dict[tuple[str, bool], Path] = {}
        for variant in selected:
            source = str((ROOT / variant["source_dir"]).resolve())
            source_key = (source, bool(variant.get("isolated_build", False)))
            if source_key not in built_sources:
                built_sources[source_key] = build_variant(variant, env, output_dir)
            actual_binaries[variant["name"]] = built_sources[source_key]
    else:
        for variant in selected:
            actual_binaries[variant["name"]] = (ROOT / variant["binary"]).resolve()

    binary_metadata = {}
    source_metadata = {}
    for variant in selected:
        binary = actual_binaries[variant["name"]]
        if not binary.is_file():
            raise FileNotFoundError(f"binary for {variant['name']} not found: {binary}")
        if not variant.get("interpreter") and not os.access(binary, os.X_OK):
            raise PermissionError(f"binary is not executable: {binary}")
        build_source = (ROOT / variant["source_dir"]).resolve()
        lockfile = build_source / "Cargo.lock"
        build_system = variant.get("build_system", "cargo")
        binary_metadata[variant["name"]] = {
            "path": str(binary),
            "sha256": sha256_file(binary),
            "build_system": build_system,
            "cargo_lock": str(lockfile) if lockfile.is_file() else None,
            "cargo_lock_sha256": sha256_file(lockfile),
            "packages": cargo_lock_versions(
                lockfile, ("rustsat", "rustsat-cadical")
            ),
            "sat_solver": variant.get(
                "sat_solver",
                "CaDiCaL via rustsat-cadical" if build_system == "cargo" else "CaDiCaL",
            ),
            "solver_seed": variant.get("solver_seed", "library default; CLI does not expose a seed"),
        }
        source = (ROOT / variant["source_dir"]).resolve()
        source_metadata[str(source)] = git_metadata(source)

    manifest = {
        "schema_version": 1,
        "created_utc": utc_now(),
        "runner": str(Path(__file__).resolve()),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "config": str(config_path),
        "config_sha256": sha256_file(config_path),
        "command": sys.argv,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node(),
            "logical_cpu_count": os.cpu_count(),
            "python": sys.version,
            "rustc": command_version(["rustc", "--version"]),
            "cargo": command_version(["cargo", "--version"]),
            "cmake": command_version(["cmake", "--version"]),
        },
        "controlled_environment": controlled_env,
        "strict_external_timeout": True,
        "timeout_sec": timeout_sec,
        "external_timeout_grace_by_variant": {
            variant["name"]: float(variant.get("external_timeout_grace_sec", 0.0))
            for variant in selected
        },
        "instance_set": args.instances or args.set_name,
        "graph_numbers": graph_numbers,
        "repetitions": args.repetitions,
        "shuffle": args.shuffle,
        "random_seed": args.random_seed,
        "stop_on_solved": args.stop_on_solved,
        "variants": selected,
        "binaries": binary_metadata,
        "sources": source_metadata,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    completed, solved_graph_repetitions = (
        load_completed(results_path) if args.resume else (set(), set())
    )
    tasks = [
        (graph_number, variant, repetition)
        for repetition in range(1, args.repetitions + 1)
        for graph_number in graph_numbers
        for variant in selected
    ]
    if args.shuffle:
        random.Random(args.random_seed).shuffle(tasks)

    graph_dir = (ROOT / config.get("graph_dir", "FHCPCS-col")).resolve()
    expected_status = config.get("expected_status", "SATISFIABLE")
    total = len(tasks)
    with results_path.open("a", encoding="utf-8", buffering=1) as results_handle:
        for task_index, (graph_number, variant, repetition) in enumerate(tasks, 1):
            key = (variant["name"], graph_number, repetition)
            if key in completed:
                print(f"[{task_index}/{total}] skip completed {key}", flush=True)
                continue
            graph_repetition = (graph_number, repetition)
            if args.stop_on_solved and graph_repetition in solved_graph_repetitions:
                print(
                    f"[{task_index}/{total}] skip portfolio-solved graph{graph_number} r{repetition}",
                    flush=True,
                )
                continue
            graph_path = graph_dir / f"graph{graph_number}.col"
            if not graph_path.is_file():
                raise FileNotFoundError(graph_path)
            features, vertices, edges = graph_features(graph_path)

            binary = actual_binaries[variant["name"]]
            artifact_variant = safe_name(variant["name"])
            artifact_stem = f"graph{graph_number}-r{repetition}"
            attempt = 1
            while True:
                attempt_suffix = "" if attempt == 1 else f"-attempt{attempt}"
                candidate_stem = f"{artifact_stem}{attempt_suffix}"
                candidate_tour = tour_dir / artifact_variant / f"{candidate_stem}.hcp.tour"
                candidate_raw = raw_dir / artifact_variant / f"{candidate_stem}.txt"
                candidate_run_dir = (
                    output_dir / "artifacts" / artifact_variant / candidate_stem
                )
                if not (
                    candidate_tour.exists()
                    or candidate_raw.exists()
                    or candidate_run_dir.exists()
                ):
                    break
                attempt += 1
            tour_path = candidate_tour
            raw_path = candidate_raw
            tour_path.parent.mkdir(parents=True, exist_ok=True)
            command = [
                *variant_command_prefix(variant, binary),
                *variant_input_argv(variant, graph_path),
                *option_argv(variant.get("options", {})),
                *[str(value) for value in variant.get("arguments", [])],
            ]
            if variant.get("supports_internal_timeout", False):
                command.extend(["--timeout", str(timeout_sec)])
            if variant.get("supports_output_tour", False):
                command.extend(["--output-tour", str(tour_path)])
            run_artifact_dir: Path | None = None
            if variant.get("supports_run_dir", False):
                run_artifact_dir = candidate_run_dir
                command.extend(["--run-dir", str(run_artifact_dir)])

            external_timeout_grace_sec = float(
                variant.get("external_timeout_grace_sec", 0.0)
            )
            if external_timeout_grace_sec < 0:
                raise ValueError(
                    f"external_timeout_grace_sec must be non-negative for {variant['name']}"
                )
            external_timeout_sec = timeout_sec + external_timeout_grace_sec

            print(
                f"[{task_index}/{total}] {variant['name']} graph{graph_number} r{repetition}",
                flush=True,
            )
            returncode, stdout, stderr, timed_out, wall_sec = run_process(
                command, external_timeout_sec, env
            )
            parsed_status = (
                "TIMEOUT"
                if timed_out
                else parse_status(stdout, str(variant.get("status_protocol", "dimacs")))
            )
            tour = parse_tour_file(tour_path) or parse_tour_stdout(stdout)
            verified, verification_reason = verify_tour(tour, vertices, edges)
            status = parsed_status
            if parsed_status == "SATISFIABLE" and not verified:
                status = "INVALID_SAT"
            elif parsed_status == "UNSATISFIABLE" and expected_status == "SATISFIABLE":
                status = "UNEXPECTED_UNSAT"
            elif parsed_status == "NO_STATUS" and returncode not in (0, 10, 20):
                status = "ERROR"

            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_text = (
                f"COMMAND: {json.dumps(command)}\n"
                f"RETURNCODE: {returncode}\n"
                f"TIMED_OUT: {timed_out}\n"
                f"WALL_SEC: {wall_sec:.9f}\n"
                "\n===== STDOUT =====\n"
                f"{stdout}"
                "\n===== STDERR =====\n"
                f"{stderr}"
            )
            raw_path.write_text(raw_text, encoding="utf-8")
            phase_stats, phase_seconds = parse_metrics(stdout)
            increment_matches = INCREMENT_RE.findall(stdout)
            clause_matches = CLAUSE_RE.findall(stdout)
            record = {
                "schema_version": 1,
                "finished_utc": utc_now(),
                "variant": variant["name"],
                "graph_number": graph_number,
                "graph": f"graph{graph_number}",
                "graph_path": str(graph_path),
                "graph_features": features,
                "repetition": repetition,
                "attempt": attempt,
                "timeout_sec": timeout_sec,
                "external_timeout_sec": external_timeout_sec,
                "external_timeout_grace_sec": external_timeout_grace_sec,
                "command": command,
                "status": status,
                "solver_status": parsed_status,
                "returncode": returncode,
                "timed_out": timed_out,
                "wall_sec": wall_sec,
                "verified": verified,
                "verification_reason": verification_reason,
                "tour_vertices": len(tour) if tour else None,
                "tour_path": str(tour_path) if tour_path.is_file() else None,
                "run_artifact_dir": str(run_artifact_dir) if run_artifact_dir else None,
                "increments": int(increment_matches[-1]) if increment_matches else None,
                "blocking_clauses": int(clause_matches[-1]) if clause_matches else None,
                "phase_stats": phase_stats,
                "phase_seconds": phase_seconds,
                "solver_stats": parse_solver_stats(stdout),
                "backend_result": parse_backend_result(stdout),
                "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
                "raw_log": str(raw_path),
            }
            results_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            results_handle.flush()
            if status == "SATISFIABLE" and verified:
                solved_graph_repetitions.add(graph_repetition)
            print(
                f"  -> {status} {wall_sec:.3f}s verified={verified} ({verification_reason})",
                flush=True,
            )

    print(f"Results: {results_path}")
    print(f"Manifest: {output_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
