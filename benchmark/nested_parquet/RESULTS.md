# Nested Parquet benchmark: read_parquet_node / read_parquet_flat

Queries of the paper "Nested Parquet Is Flat, Why Not Use It?" (Rey et al., SIGMOD 2025), from
https://github.com/alicerey/nested-parquet, on the paper's datasets (Google Drive archive linked from that repository,
8,551,262,143 bytes; the Twitter dataset is not included).

Variants per query (`queries/<dataset>/<query>.<variant>.sql`):
- `builtin`: the repository's DuckDB query over the nested file (UNNEST of nested types)
- `node`: `read_parquet_node` on the nested file with the joins on `_sk`/`_ak*` written by hand
- `flat`: the builtin query over `read_parquet_flat`, every path aliased to its short name in one subquery (this also
  exercises the analysis of the used columns). XMark has no flat version, see below
- `split`: the repository's normalized query over the paper's pre-split files with stored keys

## Running

```
python3 make_queries.py <nested-parquet repo> queries                       # builtin, node, split
python3 make_flat_queries.py <duckdb> <datasets dir> queries                 # flat
RUNS=3 [THREADS=n] python3 run_bench.py <duckdb> queries/tpch_sf1 <datasets dir>/nested-tpch results_tpch_sf1.csv
```
Dataset directories: `nested-tpch` (tpch_sf1), `nested-tpch-sf10`, `xmark`, `dblp`. Fastest of RUNS runs.
Results of all variants are compared by an order-insensitive hash (numbers rounded to 2 decimals).

## Environment

reldebug build, i7-1360P (16 hardware threads), 15 GiB, WSL2, 2026-10-15. Absolute times on this laptop vary by up to
~40% between sessions (CPU boost/thermals) - compare variants within one run. Results of an earlier run were discarded:
a stray single-threaded process occupied a core while it ran.

## Row groups of the nested files

| file | row groups | rows | writer |
|---|---|---|---|
| dblp.parquet | 6 | 6,150,738 | parquet-cpp-arrow 13 |
| nested-tpch-sf10/nestedcustomer.parquet | 22 | 1,500,000 | parquet-mr 1.13.1 |
| nested-tpch/nestedregion.parquet | 1 | 5 | parquet-cpp-arrow 13 |
| xmark/sf10.parquet | 1 | 1 | parquet-cpp-arrow 13 |
| synthetic/l0.parquet | 10 | 10,000,000 | parquet-cpp-arrow 17 |
| synthetic/l1..l6.parquet | 1 each | 10^6 .. 10 | parquet-cpp-arrow 17 |

Pre-split files: dblp 6+6, tpch-sf10 1/5/18, tpch-sf1 and xmark 1 each (`row_groups_*.csv`).

## Results (seconds, default threads = 16)

All variants return the same results for all queries.

| dataset | query | builtin | node | flat | split | builtin/node | flat/node | node/split |
|---|---|---|---|---|---|---|---|---|
| TPC-H SF1 (1 RG) | q01 | 6.3220 | 0.5550 | 0.5260 | 0.4390 | 11.39 | 0.95 | 1.26 |
|  | q03 | 5.8000 | 0.3980 | 0.3770 | 0.2600 | 14.57 | 0.95 | 1.53 |
|  | q04 | 5.8960 | 0.2770 | 0.2570 | 0.1690 | 21.29 | 0.93 | 1.64 |
|  | q06 | 5.5610 | 0.2480 | 0.2760 | 0.1760 | 22.42 | 1.11 | 1.41 |
|  | q10 | 5.6480 | 0.4020 | 0.4120 | 0.2740 | 14.05 | 1.02 | 1.47 |
|  | q12 | 5.8190 | 0.3090 | 0.2950 | 0.1930 | 18.83 | 0.95 | 1.60 |
| TPC-H SF10 (22 RG) | q01 | 5.1320 | 0.7960 | 0.7620 | 0.9240 | 6.45 | 0.96 | 0.86 |
|  | q03 | 4.3240 | 0.4400 | 0.4810 | 0.4150 | 9.83 | 1.09 | 1.06 |
|  | q04 | 4.1260 | 0.3800 | 0.4060 | 0.3160 | 10.86 | 1.07 | 1.20 |
|  | q06 | 4.2520 | 0.3120 | 0.3280 | 0.2310 | 13.63 | 1.05 | 1.35 |
|  | q12 | 4.6300 | 0.3710 | 0.3990 | 0.3480 | 12.48 | 1.08 | 1.07 |
| XMark (1 RG) | q02 | 0.7020 | 0.0430 | - | 0.0950 | 16.33 | - | 0.45 |
|  | q03 | 0.6060 | 0.0600 | - | 0.4290 | 10.10 | - | 0.14 |
|  | q04 | 0.5390 | 0.0490 | - | 0.0500 | 11.00 | - | 0.98 |
| DBLP (6 RG) | q06 | 1.1200 | 1.2610 | 1.2330 | 1.2540 | 0.89 | 0.98 | 1.01 |
|  | q07 | 1.3900 | 1.5780 | 1.6090 | 1.6290 | 0.88 | 1.02 | 0.97 |
|  | q08 | 0.4770 | 0.5010 | 0.5210 | 0.3070 | 0.95 | 1.04 | 1.63 |
|  | q09 | 0.7480 | 0.7150 | 0.7010 | 0.6320 | 1.05 | 0.98 | 1.13 |

## Threads: 1 vs 16 on the files with a single row group (seconds, fastest of 5)

| dataset | query | builtin | node | flat | split |
|---|---|---|---|---|---|
| TPC-H SF1 | q01 | 5.6940 / 6.1480 | 0.5290 / 0.5000 | 0.5260 / 0.5410 | 0.4020 / 0.4210 |
|  | q03 | 5.2990 / 5.5250 | 0.3700 / 0.3640 | 0.3460 / 0.3800 | 0.2230 / 0.2210 |
|  | q04 | 5.4780 / 5.5580 | 0.2880 / 0.2850 | 0.2700 / 0.2740 | 0.1520 / 0.1800 |
|  | q06 | 5.6640 / 5.7000 | 0.2430 / 0.2480 | 0.2600 / 0.2500 | 0.1570 / 0.1540 |
|  | q10 | 5.3200 / 5.9420 | 0.3610 / 0.3700 | 0.3760 / 0.3610 | 0.2980 / 0.2970 |
|  | q12 | 5.7800 / 5.8240 | 0.2700 / 0.2730 | 0.2950 / 0.2720 | 0.1640 / 0.1870 |
| XMark | q02 | 0.5300 / 0.5750 | 0.0480 / 0.0480 | - | 0.0850 / 0.0820 |
|  | q03 | 0.5320 / 0.5560 | 0.0540 / 0.0590 | - | 0.3850 / 0.3960 |
|  | q04 | 0.5430 / 0.5430 | 0.0470 / 0.0460 | - | 0.0470 / 0.0440 |

The number of threads makes no difference: the scans are parallelized per row group only, and the scan is the source
of the pipelines above it, so the joins and aggregations run on a single thread as well. For comparison, on TPC-H SF10
(22 row groups) Q6 takes 2.45s (node) / 2.49s (flat) with 1 thread and 0.33s / 0.35s with 16.
Parallelizing a node scan below the row group (the page jumps of the paper's Listing 3) therefore comes before filter
pushdown.

## Notes

- XMark node vs split (Q3 0.14x, Q2 0.45x): caused by the query formulation, not by the files. The repository's split
  queries find the first/last bidder with correlated subqueries (min/max `_sk` per auction `_id`), which DuckDB plans as
  CTEs with three scans of the bidders and several joins over ~1.8M intermediate rows. The node queries take
  `first()`/`last()` per `_ak1` group. With that formulation on the split files: Q2 split 0.021s vs node 0.032s, Q3 split
  0.035s vs node 0.042s (node/split 1.5x and 1.2x, in line with the other datasets).
- XMark flat: the queries need the order of the bidders of an auction, which read_parquet_flat does not expose yet.
  The paper's Umbra queries use a surrogate key pseudo-column per node (`"...bidder.sk"`).
- XMark Q4 builtin: the repository's `x -> ...` lambdas were rewritten to `lambda x: ...` (arrow lambdas are disabled
  in this build); semantics unchanged.
- A bug found by these runs and fixed: a top-level column chunk with only NULL values (DBLP `year`, row group 4) is
  skipped by the column reader without advancing its count of remaining values -> hang / TProtocolException.
