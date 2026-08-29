#!/usr/bin/env python3
"""Regression tests for the hybrid inventory and HCup runner integration."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import build_hybrid_coverage as coverage
import hcp_benchmark as runner


EXPECTED_OPEN = {
    668, 710, 717, 746, 761, 788, 809, 832, 868, 882, 937,
    944, 950, 951, 954, 959, 960, 963, 965, 966, 971, 974,
    975, 976, 981, 982, 983, 986, 987, 990, 993, 994, 998,
}


class HybridCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = coverage.load_coverage_data(
            coverage.ROOT.parent / "regression-48h.console.log"
        )
        cls.indexed = coverage.observation_index(cls.data)

    def test_paper_union_and_minimum_real_portfolio(self) -> None:
        self.assertEqual(len(self.data.paper_method_ids), 21)
        portfolio, union = coverage.minimum_portfolio_for_full_union(
            self.data.paper_method_ids, self.indexed
        )
        self.assertEqual(len(union), 968)
        self.assertEqual(set(range(1, 1002)) - union, EXPECTED_OPEN)
        self.assertEqual(len(portfolio), 4)

    def test_documented_baseline_and_interrupted_console_are_not_conflated(self) -> None:
        self.assertEqual(len(self.data.baseline_timeout_class), 75)
        regression = [
            item
            for item in self.data.observations
            if self.data.methods[item.method_id].family == "current_regression_300s"
        ]
        self.assertEqual(sum(item.status == coverage.INCOMPLETE for item in regression), 1)
        self.assertEqual(sum(item.status != coverage.INCOMPLETE for item in regression), 285)
        incomplete = next(item for item in regression if item.status == coverage.INCOMPLETE)
        self.assertEqual((incomplete.graph_number, incomplete.method_id), (982, "current300_plus_3opt"))

    def test_instance_routing_and_aggregate_only_evidence(self) -> None:
        rows, columns = coverage.build_instance_rows(self.data, self.indexed)
        by_number = {row["graph_number"]: row for row in rows}
        self.assertEqual(by_number[725]["four_stage_portfolio_method"], "ref_picat")
        self.assertEqual(by_number[725]["four_stage_portfolio_stage"], "4")
        self.assertEqual(by_number[668]["four_stage_portfolio_stage"], "OPEN")
        self.assertEqual(by_number[668]["hcup_per_instance_evidence"], "AGGREGATE_ONLY_NO_LOCAL_LOGS")
        self.assertFalse(any(column.startswith("status__hcup_") for column in columns))

    def test_generated_csvs_are_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = coverage.write_reports(self.data, Path(directory))
            counts = coverage.validate_reports(paths)
            self.assertEqual(counts["instances"], 1001)
            self.assertEqual(counts["open"], 33)
            self.assertEqual(counts["historical_open"], 33)
            with paths["methods"].open(encoding="utf-8", newline="") as handle:
                methods = {row["method_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(methods["hcup_cegar_outside_mergecutset"]["reported_solved"], "937")
            self.assertEqual(methods["hcup_vbs_propagator"]["per_instance_available"], "FALSE")
            self.assertEqual(methods["hcup_vbs_propagator"]["reported_timeout"], "")

    def test_imported_hcup_result_reduces_only_the_dynamic_open_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "results.jsonl"
            result_path.write_text(
                json.dumps(
                    {
                        "variant": "hcup_outside_mergecutset",
                        "graph_number": 668,
                        "status": "SATISFIABLE",
                        "solver_status": "SATISFIABLE",
                        "wall_sec": 12.5,
                        "timeout_sec": 1800,
                        "verified": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            data = coverage.load_coverage_data(
                coverage.ROOT.parent / "regression-48h.console.log", [result_path]
            )
            paths = coverage.write_reports(data, Path(directory) / "reports")
            counts = coverage.validate_reports(paths)
            self.assertEqual(counts["historical_open"], 33)
            self.assertEqual(counts["open"], 32)
            with paths["instances"].open(encoding="utf-8", newline="") as handle:
                graph668 = next(
                    row for row in csv.DictReader(handle) if row["graph_number"] == "668"
                )
            self.assertEqual(graph668["hcup_per_instance_evidence"], "LOCAL_RUN_SOLVED")


class RunnerCompatibilityTests(unittest.TestCase):
    def test_hcup_status_and_model_parsing(self) -> None:
        stdout = "configuration\nSAT\nMODEL: 1 3 2 4\n"
        self.assertEqual(runner.parse_status(stdout, "hcup"), "SATISFIABLE")
        self.assertEqual(runner.parse_tour_stdout(stdout), [1, 3, 2, 4])
        self.assertEqual(runner.parse_status("INTERRUPTED\n", "hcup"), "UNKNOWN")

    def test_resume_state_only_stops_after_verified_sat(self) -> None:
        rows = [
            {"variant": "a", "graph_number": 1, "repetition": 1, "status": "SATISFIABLE", "verified": True},
            {"variant": "b", "graph_number": 2, "repetition": 1, "status": "TIMEOUT", "verified": False},
            {"variant": "c", "graph_number": 3, "repetition": 1, "status": "INVALID_SAT", "verified": False},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            completed, solved = runner.load_completed(path)
        self.assertEqual(len(completed), 3)
        self.assertEqual(solved, {(1, 1)})


if __name__ == "__main__":
    unittest.main()
