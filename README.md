# SAT-based-CEGAR / HCP Solver

> **Original Work & Attribution:** This repository is based on and extends the Hamiltonian Cycle Problem (HCP) SAT-based CEGAR solver developed by **Takehide Soh** (Kobe University, Japan) at [`https://github.com/TakehideSoh/SAT-based-CEGAR`](https://github.com/TakehideSoh/SAT-based-CEGAR).

---

## 1. Overview & Components

- **`src/cegar-fix`**: Native Rust-based Hamiltonian Cycle Solver utilizing in-Rust CNF encoding, incremental CaDiCaL SAT solving (via `rustsat`), multi-level 2-opt/3-opt cycle patching, MTZ stall injection, and degree-2 contraction.
- **`docs/`**: Comprehensive technical architecture documentation, benchmark analyses, and experimental reports:
  - [`docs/rust_solver_architecture_and_methods.md`](docs/rust_solver_architecture_and_methods.md): Full technical breakdown of all algorithms and CLI flags in the Rust codebase (`cegar-fix`).
  - [`docs/graph950_methods_and_experiments_report.md`](docs/graph950_methods_and_experiments_report.md): Deep-dive research report on methods attempted on `graph950.col`.
- [`docs/timeout-classification-analysis.md`](docs/timeout-classification-analysis.md): Systematic categorization of timeout dynamics across 1,001 FHCP benchmark instances.
- [`docs/hybrid-coverage.md`](docs/hybrid-coverage.md): Per-instance CSV inventory, exact portfolio coverage, HCup integration, and a resumable 1–2 day run plan for the 33 remaining instances.
- [`docs/adaptive-hybrid-sat-hcp.tex`](docs/adaptive-hybrid-sat-hcp.tex): Beginner-friendly Vietnamese LaTeX document explaining SAT, CEGAR, HCup, and the proposed Adaptive Hybrid SAT-HCP method. The compiled PDF is in [`output/pdf/adaptive-hybrid-sat-hcp.pdf`](output/pdf/adaptive-hybrid-sat-hcp.pdf).
- **`logs/`**: Consolidated experimental logs, runtime data CSVs, and sample JSONs across the 1,001 FHCPCS benchmark graphs.
- **`scratch/`**: Prototyping scripts, two-tier decomposition experiments, and verification tools.

---

## 2. Solvers & Libraries

- **CaDiCaL** (<https://github.com/arminbiere/cadical> version 1.9.4 / 1.9.5)
- **rustsat** (<https://github.com/chrjabs/rustsat> version 0.6.1)
- **PySAT** (`pysat.solvers.Cadical195`) for Python-based decomposition prototypes.

---

## 3. Build & Execution

### Build Release Binary
```bash
cd src/cegar-fix
cargo build --release
```

### Execution Example
```bash
./src/cegar-fix/target/release/cegar-fix -i FHCPCS-col/graph1.col -e 1 -b 3 -y 3 -t 3 -l 1
```

### Reproducible A/B Benchmark

```bash
./run_tests.sh
python3 tools/hcp_benchmark.py --set regression_core --timeout 1800
```

The runner records an immutable manifest, JSONL results, raw logs, feature telemetry, and independently verifies every SAT tour. See [`docs/reproducible-benchmark.md`](docs/reproducible-benchmark.md).

### Adaptive Hybrid SAT-HCP (AHS v0)

AHS v0 runs the strongest replayed CEGAR configuration and HCup-HFP under one total budget. It routes only from reproducible graph features and accepts SAT only after independent tour verification.

```bash
./run_ahs.sh --build-only
./run_ahs.sh --input FHCPCS-col/graph950.col --timeout 1800 --no-build
./run_ahs_benchmark.sh --timeout 1800 --output benchmark-runs/ahs-open33-1800s
```

Implementation details, artifacts, policy fractions, and current limitations are documented in [`docs/ahs-implementation.md`](docs/ahs-implementation.md).

For full CLI options and algorithmic descriptions, please refer to [`docs/rust_solver_architecture_and_methods.md`](docs/rust_solver_architecture_and_methods.md).

---

## 4. Citation & Reference

If you use or reference this codebase, please cite the upstream original work:
- **Author:** Takehide Soh (Kobe University, Japan)
- **Upstream Repository:** [https://github.com/TakehideSoh/SAT-based-CEGAR](https://github.com/TakehideSoh/SAT-based-CEGAR)
