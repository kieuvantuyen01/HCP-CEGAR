#!/usr/bin/env python3
"""Unit tests for the AHS policy, budget, verification, and outcome rules."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import ahs_solver as ahs
import hcp_benchmark as runner


class AhsPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = ahs.load_config(ahs.DEFAULT_CONFIG)

    def test_default_config_is_valid_and_deterministic(self) -> None:
        self.assertEqual(self.config["default_policy"], "rule_v2")
        self.assertEqual(self.config["controller"]["type"], "fixed_rules")
        self.assertIs(self.config["controller"]["uses_machine_learning"], False)
        self.assertEqual(
            ahs.policy_backend_names(self.config, "rule_v2"),
            [
                "hcup_outside_mergecutset",
                "cegar_sinz_2loop_2opt3",
                "hcup_hfp_preventsubcycle",
            ],
        )

    def test_residual_policy_does_not_repeat_known_cegar_misses(self) -> None:
        self.assertEqual(
            ahs.policy_backend_names(self.config, "residual_v1"),
            ["hcup_outside_mergecutset", "hcup_hfp_preventsubcycle"],
        )

    def test_invalid_fraction_sum_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["policies"]["rule_v2"]["routes"]["dense"][0]["fraction"] = 0.8
        with self.assertRaisesRegex(ValueError, "fractions sum"):
            ahs.validate_config(config)

    def test_boolean_fraction_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["policies"]["cegar_only"]["routes"]["dense"][0]["fraction"] = True
        with self.assertRaisesRegex(ValueError, "invalid fraction"):
            ahs.validate_config(config)

    def test_nan_fraction_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["policies"]["cegar_only"]["routes"]["dense"][0]["fraction"] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid fraction"):
            ahs.validate_config(config)

    def test_route_uses_features_not_graph_number(self) -> None:
        self.assertEqual(ahs.classify_route({"m_over_n": 3.0, "degree2_fraction": 0.8}), "dense")
        self.assertEqual(
            ahs.classify_route({"m_over_n": 2.9, "degree2_fraction": 0.10001}),
            "sparse_degree2",
        )
        self.assertEqual(
            ahs.classify_route({"m_over_n": 2.9, "degree2_fraction": 0.10}),
            "sparse_other",
        )

    def test_cumulative_deadlines_allow_unused_time_to_carry_forward(self) -> None:
        stages = self.config["policies"]["rule_v2"]["routes"]["sparse_other"]
        self.assertEqual(ahs.cumulative_stage_fractions(stages), [0.45, 0.8, 1.0])

    def test_transition_reason_uses_only_observed_stage_status(self) -> None:
        self.assertEqual(ahs.transition_reason([]), "policy_route_start")
        self.assertEqual(
            ahs.transition_reason([{"status": "TIMEOUT", "graph_number": 950}]),
            "previous_stage_timeout",
        )

    def test_machine_learning_controller_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["controller"] = {
            "type": "learned_selector",
            "uses_machine_learning": True,
        }
        with self.assertRaisesRegex(ValueError, "fixed_rules"):
            ahs.validate_config(config)

    def test_default_policy_does_not_use_invalid_ccad_compatibility_replay(self) -> None:
        self.assertNotIn(
            "paper_ccad_best_replay",
            ahs.policy_backend_names(self.config, self.config["default_policy"]),
        )

    def test_hcup_activity_is_machine_readable(self) -> None:
        activity = runner.parse_hcup_activity(
            "ASSIGNMENTS: 1\n"
            "DECISION LEVEL: 2\n"
            "BACKTRACK: 3\n"
            "PROPAGATE: 4\n"
            "ADD REASON: 5\n"
            "FOUND MODELs: 6\n"
            "EXTERNAL CLAUSE EARLY CYCLE DETECTION: 7\n"
            "EXTERNAL BLOCKING CLAUSE AVG SIZE: 8\n"
            "EXTERNAL BLOCKING CLAUSE REPORTED: 9\n"
            "ASSIGNMENTS:                                     11\n"
            "DECISION LEVEL:                                  12\n"
            "BACKTRACK:                                       13\n"
            "PROPAGATE:                                       14\n"
            "ADD REASON:                                      15\n"
            "FOUND MODELs:                                    16\n"
            "EXTERNAL CLAUSE EARLY CYCLE DETECTION:           17\n"
            "EXTERNAL BLOCKING CLAUSE AVG SIZE:               18\n"
            "EXTERNAL BLOCKING CLAUSE REPORTED:               19\n"
        )
        self.assertEqual(
            activity,
            {
                "assignments": 11,
                "decision_level": 12,
                "backtracks": 13,
                "propagations": 14,
                "reasons": 15,
                "models": 16,
                "early_cycle_clauses": 17,
                "avg_blocking_clause_size": 18,
                "blocking_clauses_reported": 19,
            },
        )

    def test_backend_result_parser_keeps_last_json_event(self) -> None:
        result = runner.parse_backend_result(
            'c result_json={"policy":"old"}\n'
            'c result_json={"policy":"rule_v2","budget_exhausted":false}\n'
        )
        self.assertEqual(result, {"policy": "rule_v2", "budget_exhausted": False})

    def test_outer_runner_extracts_portfolio_stage_telemetry(self) -> None:
        stages = [{"backend": "cegar", "increments": 7}]
        self.assertEqual(
            runner.extract_portfolio_stage_results({"stage_results": stages}), stages
        )
        self.assertIsNone(runner.extract_portfolio_stage_results({"stage_results": [1]}))
        self.assertIsNone(runner.extract_portfolio_stage_results(None))

    def test_skipped_stage_uses_the_stable_event_schema(self) -> None:
        result = ahs.skipped_stage_result(
            {"backend": "later", "fraction": 0.2},
            stage_index=3,
            cumulative_fraction=1.0,
            usable_budget=98.0,
            reason="previous_stage_timeout",
        )
        event = ahs.stage_result_event(result)
        self.assertEqual(set(event), set(ahs.STAGE_EVENT_FIELDS))
        self.assertEqual(event["stage_index"], 3)
        self.assertEqual(event["deadline_from_budget_start_sec"], 98.0)
        self.assertEqual(event["status"], "SKIPPED_NO_BUDGET")
        self.assertEqual(event["phase_stats"], {})

    def test_residual_wrapper_rejects_scope_overrides_before_build(self) -> None:
        result = subprocess.run(
            [str(ahs.ROOT / "run_ahs_residual33.sh"), "--variants", "ahs_rule_v2"],
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("fixes config, set, and variant", result.stderr)

    def test_general_wrapper_rejects_config_override_before_build(self) -> None:
        result = subprocess.run(
            [str(ahs.ROOT / "run_ahs_benchmark.sh"), "--config", "other.json"],
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("fixes the AHS config", result.stderr)


class AhsVerificationTests(unittest.TestCase):
    def test_written_tour_round_trips_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cycle.tour"
            ahs.write_tour(path, [1, 2, 3, 4], "cycle4")
            tour = runner.parse_tour_file(path)
            verified, reason = runner.verify_tour(
                tour,
                {1, 2, 3, 4},
                {(1, 2), (2, 3), (3, 4), (1, 4)},
            )
        self.assertTrue(verified)
        self.assertEqual(reason, "verified")

    def test_invalid_sat_is_a_hard_failure_after_portfolio_exhaustion(self) -> None:
        self.assertEqual(
            ahs.exhausted_status([{"status": "TIMEOUT"}, {"status": "INVALID_SAT"}]),
            "ERROR",
        )
        self.assertEqual(
            ahs.exhausted_status([{"status": "TIMEOUT"}, {"status": "UNKNOWN"}]),
            "UNKNOWN",
        )

    def test_run_stage_rejects_an_invalid_sat_tour(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            backend_binary = temp / "invalid_backend.py"
            backend_binary.write_text(
                "#!/usr/bin/env python3\n"
                "print('solution:')\n"
                "print('1 3 2 4')\n"
                "print('s SATISFIABLE')\n",
                encoding="utf-8",
            )
            os.chmod(backend_binary, 0o755)
            result, tour = ahs.run_stage(
                {
                    "name": "invalid",
                    "source_dir": str(temp),
                    "binary": str(backend_binary),
                    "build_system": "none",
                    "trust_unsat": True,
                },
                backend_binary,
                temp / "unused.col",
                2.0,
                {1, 2, 3, 4},
                {(1, 2), (2, 3), (3, 4), (1, 4)},
                temp / "raw.txt",
                os.environ.copy(),
            )
            self.assertEqual(tour, [1, 3, 2, 4])
            self.assertEqual(result["status"], "INVALID_SAT")
            self.assertFalse(result["verified"])
            self.assertTrue(result["verification_reason"].startswith("missing_edge:"))

    def test_run_stage_enforces_external_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            backend_binary = temp / "slow_backend.py"
            backend_binary.write_text(
                "#!/usr/bin/env python3\n"
                "import time\n"
                "time.sleep(5)\n",
                encoding="utf-8",
            )
            os.chmod(backend_binary, 0o755)
            started = time.perf_counter()
            result, tour = ahs.run_stage(
                {
                    "name": "slow",
                    "source_dir": str(temp),
                    "binary": str(backend_binary),
                    "build_system": "none",
                    "trust_unsat": True,
                },
                backend_binary,
                temp / "unused.col",
                0.1,
                {1, 2, 3},
                {(1, 2), (2, 3), (1, 3)},
                temp / "raw.txt",
                os.environ.copy(),
            )
            elapsed = time.perf_counter() - started
            self.assertIsNone(tour)
            self.assertEqual(result["status"], "TIMEOUT")
            self.assertTrue(result["timed_out"])
            self.assertLess(elapsed, 2.0)

    def test_run_stage_preserves_backend_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            backend_binary = temp / "telemetry_backend.py"
            backend_binary.write_text(
                "#!/usr/bin/env python3\n"
                "print('c metric phase=repair iteration=3 seconds=0.25 cycles_before=4 cycles_after=2')\n"
                "print('c solver_stats iteration=3 conflicts=7 decisions=9 propagations=11 clauses=13 variables=17 avg_clause_len=2.5 cpu_solve_seconds=0.2')\n"
                "print('overall incremented number = 3')\n"
                "print('overall number of added block clauses = 5')\n"
                "print('solution:')\n"
                "print('1 2 3 4')\n"
                "print('s SATISFIABLE')\n",
                encoding="utf-8",
            )
            os.chmod(backend_binary, 0o755)
            result, _ = ahs.run_stage(
                {
                    "name": "telemetry",
                    "source_dir": str(temp),
                    "binary": str(backend_binary),
                    "build_system": "none",
                    "trust_unsat": True,
                },
                backend_binary,
                temp / "unused.col",
                2.0,
                {1, 2, 3, 4},
                {(1, 2), (2, 3), (3, 4), (1, 4)},
                temp / "raw.txt",
                os.environ.copy(),
            )
            self.assertEqual(result["increments"], 3)
            self.assertEqual(result["blocking_clauses"], 5)
            self.assertEqual(result["phase_stats"]["repair"]["calls"], 1)
            self.assertEqual(result["phase_stats"]["repair"]["cycle_reduction_total"], 2)
            self.assertEqual(result["solver_stats"]["conflicts"], 7)

    def test_end_to_end_accepts_only_a_verified_fake_backend_tour(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            graph = temp / "cycle4.col"
            graph.write_text(
                "p 4 4\ne 1 2\ne 2 3\ne 3 4\ne 4 1\n", encoding="utf-8"
            )
            backend = temp / "fake_backend.py"
            backend.write_text(
                "#!/usr/bin/env python3\n"
                "print('overall incremented number = 3')\n"
                "print('overall number of added block clauses = 5')\n"
                "print('solution:')\n"
                "print('1 2 3 4')\n"
                "print('s SATISFIABLE')\n",
                encoding="utf-8",
            )
            os.chmod(backend, 0o755)
            routes = {
                family: [{"backend": "fake", "fraction": 1.0}]
                for family in ("dense", "sparse_degree2", "sparse_other")
            }
            config = temp / "policy.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "default_policy": "test",
                        "controller": {
                            "type": "fixed_rules",
                            "uses_machine_learning": False,
                        },
                        "routing": {
                            "dense_m_over_n_min": 3.0,
                            "degree2_fraction_min_exclusive": 0.1,
                        },
                        "backends": [
                            {
                                "name": "fake",
                                "source_dir": str(temp),
                                "binary": str(backend),
                                "build_system": "none",
                                "trust_unsat": True,
                            }
                        ],
                        "policies": {"test": {"routes": routes}},
                    }
                ),
                encoding="utf-8",
            )
            output_tour = temp / "verified.tour"
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(ahs.__file__).resolve()),
                    "--config",
                    str(config),
                    "--input",
                    str(graph),
                    "--timeout",
                    "5",
                    "--shutdown-reserve",
                    "0.5",
                    "--no-build",
                    "--run-dir",
                    str(temp / "run"),
                    "--output-tour",
                    str(output_tour),
                ],
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 10, result.stderr)
            self.assertIn("s SATISFIABLE", result.stdout)
            backend_result = runner.parse_backend_result(result.stdout)
            self.assertIsNotNone(backend_result)
            self.assertEqual(backend_result["schema_version"], 1)
            self.assertEqual(backend_result["stage_schema_version"], 1)
            stage = backend_result["stage_results"][0]
            self.assertEqual(stage["increments"], 3)
            self.assertEqual(stage["blocking_clauses"], 5)
            self.assertEqual(stage["stage_index"], 1)
            verified_tour = runner.parse_tour_file(output_tour)
            verified, reason = runner.verify_tour(
                verified_tour,
                {1, 2, 3, 4},
                {(1, 2), (2, 3), (3, 4), (1, 4)},
            )
            self.assertTrue(verified, reason)


if __name__ == "__main__":
    unittest.main()
