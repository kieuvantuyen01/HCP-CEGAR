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
        self.assertEqual(self.config["default_policy"], "rule_v1")
        self.assertEqual(self.config["controller"]["type"], "fixed_rules")
        self.assertIs(self.config["controller"]["uses_machine_learning"], False)
        self.assertEqual(
            ahs.policy_backend_names(self.config, "rule_v1"),
            ["paper_ccad_best_replay", "hcup_hfp_preventsubcycle"],
        )

    def test_invalid_fraction_sum_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["policies"]["rule_v1"]["routes"]["dense"][0]["fraction"] = 0.8
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
        stages = self.config["policies"]["rule_v1"]["routes"]["sparse_other"]
        self.assertEqual(ahs.cumulative_stage_fractions(stages), [0.8, 1.0])

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

    def test_cegar_ffi_build_has_no_machine_specific_link_paths(self) -> None:
        build_script = (ahs.ROOT / "src/cegar-ffi/build.rs").read_text(encoding="utf-8")
        self.assertNotIn("/home/", build_script)
        self.assertNotIn("/work/", build_script)
        self.assertIn("CADICAL_DIR", build_script)


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
            verified_tour = runner.parse_tour_file(output_tour)
            verified, reason = runner.verify_tour(
                verified_tour,
                {1, 2, 3, 4},
                {(1, 2), (2, 3), (3, 4), (1, 4)},
            )
            self.assertTrue(verified, reason)


if __name__ == "__main__":
    unittest.main()
