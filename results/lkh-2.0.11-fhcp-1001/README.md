# LKH 2.0.11 on the FHCP Challenge Set

This directory contains the filtered per-instance results of one LKH 2.0.11
run on each of the 1,001 FHCP Challenge instances.

## Configuration

- LKH version: 2.0.11
- Random seed: 1
- `RUNS`: 2,000,000 (a nonbinding restart ceiling)
- Per-instance wall-clock limit: 1,800 seconds
- Per-instance process-tree memory limit: 7,168 MB
- Outcome validation: every reported tour was independently checked against
  the original FHCP graph

The workload was split across two matching compute hosts. The first phase ran
one LKH process per host. To complete the registered matrix, the unfinished
instances were divided into two disjoint continuation streams per host, pinned
to separate physical cores. No instance was rerun and every graph has exactly
one final record.

## Aggregate outcomes

| Measure | Result |
|---|---:|
| Instances | 1,001 |
| Independently verified Hamiltonian cycles | 256 |
| Timeouts | 745 |
| Verified cycles found within 10 s | 178 |
| Verified cycles found within 100 s | 225 |
| Median solved-run time | 1.60 s |
| Solved-run time IQR | [0.40, 14.52] s |
| Descriptive PAR-2 | 2,695.953 s |
| Primary certificate cases solved | 0 / 12 |
| Residual-29 cases solved | 0 / 29 |

LKH is used here as a certificate-finding heuristic. `TIMEOUT` therefore means
that no valid tour was found within the resource limit; it is not an UNSAT
conclusion. Because this is a one-seed run and the continuation phase changed
only the scheduling concurrency, the dataset supports certificate coverage and
descriptive time-to-certificate summaries. It does not support claims about
seed robustness, stochastic variance, or fine-grained cross-method runtime
superiority.

## Files

- `results.jsonl`: one sanitized record per graph, sorted by graph number.
  Machine names, user paths, commands, repository state, and binary hashes were
  removed from the downloaded records.
- `summary.json`: aggregate values recomputed from `results.jsonl`.
- `verify_results.py`: validates completeness, fixed configuration fields,
  unique graph IDs, certificate flags, and the aggregate summary.

Run the independent consistency check with:

```bash
python3 verify_results.py --check-summary summary.json
```

PAR-2 charges every unsolved instance twice the 1,800-second cutoff. Runtime
quartiles use linear interpolation over the verified solved runs.
