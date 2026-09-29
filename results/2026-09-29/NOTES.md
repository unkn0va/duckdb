# Final measurement — 2026-09-29, apache10

DuckDB `a85216b8b7` (prenest-3way, includes the untraceable-read fix 753246123e).
DataFusion: see datafusion_head.txt; runner state in datafusion_runner.diff.
Data /data/tpch-nested/1/ (SF1). Machine idle during all runs (1 user, load < 1).
Runs were strictly sequential; nothing else ran on the machine.

## Method
- DuckDB: scripts/bench_prenest_timing.sh. Fresh process per run, 6 runs, first
  discarded, median of 5, /usr/bin/time -f %e (0.01 s resolution), startup included.
  Same loop as results/2026-09-17 and 2026-09-19 (recovered from shell history).
- DataFusion: benchmarks/run_nested_benchmark.sh with run_active.
  ratio = col_prune / push_deep_scan.
- Both systems measured twice.

## Plans unchanged
elements_appended for all 27 queries identical to results/2026-09-19.

## Noise
Queries where the pass does nothing (q2 q9 q9b q13 q16 q17 q18 q22; all optimizer
counters 0) range 0.88–1.10 for DuckDB, 0.93–1.05 for DataFusion.

## Date effect, not code
Several DuckDB ratios are lower than 2026-09-19 (q6 4.35 -> 3.92/4.08, q4, q10).
A/B on the same day: 7618e48fb9 (the 09-19 binary) rebuilt and run today gives
q6 3.920 vs 3.916/4.083 for a85216b8b7. DataFusion, whose code did not change,
moved the same direction (q12 2.17 on 09-17 -> 1.71/1.78). Compare same-day pairs only.

## Result (22 common queries)
Same 13 queries gain beyond noise in both systems:
q3 q4 q5 q6 q7 q8 q10 q12 q14 q15 q19 q20 q21. DataFusion q1 is borderline (1.09/1.07).

| query | DuckDB run1/run2 | DataFusion run1/run2 |
|---|---|---|
| q6  | 3.92 / 4.08 | 1.75 / 1.86 |
| q12 | 4.36 / 4.38 | 1.71 / 1.78 |
| q3  | 2.84 / 2.87 | 1.24 / 1.15 |
| geomean of the 13 | 2.66 | 1.37 |

## Caveats
- Each ratio is within one system against its own baseline, not a cross-engine speed comparison.
- DuckDB timing includes process startup, which understates its ratios.
- Supersedes the earlier "4.318 / 3.406 / 1.764" table, which was measured on
  code before 7618e48fb9 (weaker predicate expressivity).
