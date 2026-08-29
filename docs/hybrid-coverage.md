# Hybrid coverage inventory

This workflow answers two different questions without mixing them:

1. Which FHCP instances have already been solved by a method for which local per-instance evidence exists?
2. Which methods report a strong aggregate total, but still need per-instance logs before their complementary coverage can be measured?

## Current picture

The 21 paper/reference configurations with complete per-instance CSV data have a virtual-best union of **968/1001**. An exhaustive set-cover check proves that at least four real configurations are required to reproduce that union. The ordered fallback schedule in `hybrid-portfolio-summary.csv` is:

| Stage | Configuration | Solved alone | New at stage | Cumulative |
|---:|---|---:|---:|---:|
| 1 | ccad 2loop + asym3 + 2opt3 | 957 | 957 | 957 |
| 2 | ASP | 942 | 8 | 965 |
| 3 | Sinz 2loop | 884 | 2 | 967 |
| 4 | Picat | 428 | 1 | 968 |

The 33 instances outside that union comprise 24 Class B2b sparse/degree-2 instances, six Class B1 dense instances, and three Class B2a merge-stall instances. These are the right initial target for new HCup runs.

The interrupted 48-hour regression log contains **285 completed tasks, one started-but-incomplete task, and 194 tasks that were never started**. Its six solved graph IDs were already covered by earlier methods; it currently adds no instance to the 968 union. Missing tasks are recorded as `MISSING`, never as `TIMEOUT`.

The HCup paper reports 937 solved for `outside-mergecutset`, 917 for `hfp-preventsubcycle`, 943 for VBS-cegar, and 961 for VBS-propagator. All rows from Tables 5.2 and 5.3 are included in the method summary. Because the HCup per-instance logs are not present locally, these aggregate totals are not used to claim a union larger than 968. VBS rows are oracle summaries, not runnable single solvers.

## Generated CSV files

Run:

```bash
python3 tools/build_hybrid_coverage.py
```

The command writes:

- `reports/hybrid-coverage/hybrid-instance-coverage.csv`: one row for every graph, structural features, coverage/routing fields, and one status column for every method with per-instance evidence.
- `reports/hybrid-coverage/hybrid-run-observations.csv`: normalized long-form observations with source, timeout, verification, and notes.
- `reports/hybrid-coverage/hybrid-method-summary.csv`: comparable per-method counts plus aggregate-only HCup results.
- `reports/hybrid-coverage/hybrid-portfolio-summary.csv`: the four-stage historical fallback portfolio and its marginal gains.
- `reports/hybrid-coverage/hybrid-historical-open-instances.csv`: the fixed 33-instance research core not solved by any of the 21 complete paper/reference columns.
- `reports/hybrid-coverage/hybrid-open-instances.csv`: the dynamic residual after all currently imported per-instance runs. This file will shrink when new verified HCup results are imported.

Status values are `SOLVED`, `TIMEOUT`, `INCOMPLETE`, `ERROR`, and `MISSING`. `SOLVED` from the reproducible runner requires a tour that passes graph-level verification.

## Run the next hybrid stage

Place the HCup repository next to this repository, including its CaDiCaL submodule:

```text
parent/
├── HCP/
└── hcup/
```

The public fork includes the Clang/Apple-Silicon portability fixes used by the smoke test:

```bash
git clone --recurse-submodules https://github.com/kieuvantuyen01/Hcup.git hcup
```

The hybrid config contains the two most promising new complementary configurations as defaults. It builds HCup with CMake, runs configurations in order, verifies `MODEL:` output, and stops later stages for an instance after the first verified solution:

```bash
python3 tools/hcp_benchmark.py \
  --config benchmarks/hybrid_variants.json \
  --set historical_open_33 \
  --stop-on-solved \
  --output benchmark-runs/hcup-open33
```

At a 1,800-second cap, the worst-case sequential budget is 33 hours for two configurations. `--stop-on-solved` normally lowers it. To resume safely after interruption:

```bash
python3 tools/hcp_benchmark.py \
  --config benchmarks/hybrid_variants.json \
  --set historical_open_33 \
  --stop-on-solved \
  --no-build \
  --resume \
  --output benchmark-runs/hcup-open33
```

On a machine with at least two suitable CPU cores and enough memory for two simultaneous HCup processes, split the set between two terminals. Each shard has a worst-case wall budget of about 17 hours:

```bash
# terminal 1
python3 tools/hcp_benchmark.py --config benchmarks/hybrid_variants.json \
  --instances 668,717,761,809,868,937,950,954,960,965,971,975,981,983,987,993,998 \
  --stop-on-solved --output benchmark-runs/hcup-open33-a

# terminal 2
python3 tools/hcp_benchmark.py --config benchmarks/hybrid_variants.json \
  --instances 710,746,788,832,882,944,951,959,963,966,974,976,982,986,990,994 \
  --stop-on-solved --output benchmark-runs/hcup-open33-b
```

Do not run two shards if memory is tight; the paper used a 7 GB per-process limit.

## Merge new evidence

The inventory accepts any number of runner JSONL files:

```bash
python3 tools/build_hybrid_coverage.py \
  --benchmark-results benchmark-runs/hcup-open33-a/results.jsonl \
  --benchmark-results benchmark-runs/hcup-open33-b/results.jsonl
```

After the merge, inspect `hybrid-open-instances.csv`. Run the optional `current_full` and `hcup_outside_mergecutset_plain` stages only on the remaining graph IDs, rather than paying their cost on all 1,001 instances. The aggregate paper result shows that the plain variant has five unique wins over full merge-cutset, so it belongs late in the portfolio rather than at the front.

## Verification

```bash
python3 tools/test_hybrid_coverage.py
```

The tests pin the 968 union, exact four-method lower bound, 33 historical open IDs, 75 documented baseline timeouts, interrupted-log semantics, HCup output parsing, resume behavior, and the dynamic reduction of the open list after importing a verified result.
