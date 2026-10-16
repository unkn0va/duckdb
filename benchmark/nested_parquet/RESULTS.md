# Nested Parquet benchmark: read_parquet_node / read_parquet_flat

Queries of the paper "Nested Parquet Is Flat, Why Not Use It?" (Rey et al., SIGMOD 2025), from
https://github.com/alicerey/nested-parquet, on the paper's datasets (Google Drive archive linked from that repository,
8,551,262,143 bytes; the Twitter dataset is not included).

Variants per query (`queries/<dataset>/<query>.<variant>.sql`):
- `builtin`: the repository's DuckDB query over the nested file (UNNEST of nested types)
- `node`: `read_parquet_node` on the nested file with the joins on `_sk`/`_ak*` written by hand
- `flat`: the builtin query over `read_parquet_flat`, every path aliased to its short name in one subquery (this also
  exercises the analysis of the used columns)
- `flat_umbra` / `flat_minmax` (XMark): the element order through the `"<path>._sk"` columns of `read_parquet_flat` -
  Umbra's queries translated as they are (correlated subqueries with min/max of the key per auction `_id`), and a join
  with the min/max key per parent (`GROUP BY "open_auctions.open_auction._sk"`)
- `split`: the repository's normalized query over the paper's pre-split files with stored keys

A variant's result is compared with the builtin one by an order-insensitive hash (numbers rounded to 2 decimals), or
with `<query>.<variant>.oracle` where the variant has a different result by definition (see XMark below).
**All variants return their expected result for all queries, with both binaries and both thread counts.**

## Running

```
python3 make_queries.py <nested-parquet repo> queries                       # builtin, node, split
python3 make_flat_queries.py <duckdb> <datasets dir> queries                 # flat
RUNS=5 THREADS=1,16 python3 run_bench.py base=<old duckdb>,new=<duckdb> queries/xmark <datasets dir>/xmark parallel_xmark.csv
```
Dataset directories: `nested-tpch` (tpch_sf1), `nested-tpch-sf10`, `xmark`, `dblp`. Fastest of RUNS runs.

## Method

reldebug builds, i7-1360P (16 hardware threads), 15 GiB, WSL2, 2026-10-16.

- The timings of this laptop drift by tens of percent within an hour: the same builtin TPC-H SF1 query took 5.7s in
  one run and 3.5s ten minutes later. Binaries and thread counts are therefore compared **interleaved**: for every
  query and variant, all configurations run one after the other (`base`/`new` x `threads=1`/`16`). Differences between
  separate runs are not meaningful.
- Within a run the noise is still visible: the builtin and split variants, whose code did not change, have
  new/base ratios of 0.91-1.04 with 1 thread and 0.77-1.27 with 16 threads.
- `run_bench.py` samples the CPU use of other processes before every query (column `busy_cpu`) and warns above 50% of
  a core. An earlier run was discarded after a stray single-threaded process was found to occupy a core during it.
- `base` = the build before the parallel scan (with `"<path>._sk"`), `new` = with the parallel scan.

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

## Results (seconds, `new` binary, 16 threads)

| dataset | query | builtin | node | flat | flat_umbra | flat_minmax | split | builtin/node | node/split |
|---|---|---|---|---|---|---|---|---|---|
| TPC-H SF1 (1 RG) | q01 | 3.808 | 0.166 | 0.150 | - | - | 0.264 | 22.94 | 0.63 |
|  | q03 | 3.527 | 0.159 | 0.148 | - | - | 0.164 | 22.18 | 0.97 |
|  | q04 | 3.427 | 0.095 | 0.087 | - | - | 0.111 | 36.07 | 0.86 |
|  | q06 | 3.727 | 0.068 | 0.077 | - | - | 0.112 | 54.81 | 0.61 |
|  | q10 | 3.349 | 0.163 | 0.144 | - | - | 0.184 | 20.55 | 0.89 |
|  | q12 | 4.046 | 0.119 | 0.099 | - | - | 0.119 | 34.00 | 1.00 |
| TPC-H SF10 (22 RG) | q01 | 4.092 | 0.623 | 0.633 | - | - | 0.510 | 6.57 | 1.22 |
|  | q03 | 3.614 | 0.368 | 0.374 | - | - | 0.320 | 9.82 | 1.15 |
|  | q04 | 4.317 | 0.351 | 0.335 | - | - | 0.255 | 12.30 | 1.38 |
|  | q06 | 3.564 | 0.268 | 0.266 | - | - | 0.177 | 13.30 | 1.51 |
|  | q12 | 4.928 | 0.371 | 0.320 | - | - | 0.267 | 13.28 | 1.39 |
| XMark (1 RG) | q02 | 0.346 | 0.015 | - | 0.041 | 0.024 | 0.055 | 23.07 | 0.27 |
|  | q03 | 0.337 | 0.021 | - | 0.125 | 0.046 | 0.220 | 16.05 | 0.10 |
|  | q04 | 0.354 | 0.016 | - | 0.036 | 0.025 | 0.027 | 22.12 | 0.59 |
|  | q04p | 0.349 | 0.020 | - | 0.039 | 0.028 | 0.048 | 17.45 | 0.42 |
| DBLP (6 RG) | q06 | 0.746 | 0.607 | 0.809 | - | - | 1.088 | 1.23 | 0.56 |
|  | q07 | 1.054 | 0.808 | 0.801 | - | - | 1.157 | 1.30 | 0.70 |
|  | q08 | 0.311 | 0.273 | 0.305 | - | - | 0.235 | 1.14 | 1.16 |
|  | q09 | 0.602 | 0.346 | 0.340 | - | - | 0.414 | 1.74 | 0.84 |

## Parallel scan below the row group: threads=1 and threads=16

Before, a node scan was parallelized per row group only: on the files with a single row group, every variant took
the same time with 1 and 16 threads, as the scan is the source of the pipelines above it. Now a row group is split
into ranges of slots when the file has fewer row groups than threads; the keys at the start of a range are computed
by a parallel pre-pass that reads only the repetition levels of the node's cheapest column, and only for the ancestor
keys that are used. With 1 thread, or when a row group is not split, the scan is the one from before.

Seconds, fastest of 5, `base` -> `new` interleaved (t1 ratio: new/base, < 1 is faster; t16: base/new speedup):

| dataset | query | variant | base t1 | new t1 | t1 new/base | base t16 | new t16 | t16 speedup |
|---|---|---|---|---|---|---|---|---|
| TPC-H SF1 (1 RG) | q01 | node | 0.355 | 0.347 | 0.98 | 0.351 | 0.166 | 2.11x |
|  | q01 | flat | 0.354 | 0.339 | 0.96 | 0.347 | 0.150 | 2.31x |
|  | q03 | node | 0.231 | 0.248 | 1.07 | 0.238 | 0.159 | 1.50x |
|  | q03 | flat | 0.247 | 0.225 | 0.91 | 0.240 | 0.148 | 1.62x |
|  | q04 | node | 0.178 | 0.179 | 1.01 | 0.182 | 0.095 | 1.92x |
|  | q04 | flat | 0.176 | 0.177 | 1.01 | 0.177 | 0.087 | 2.03x |
|  | q06 | node | 0.160 | 0.160 | 1.00 | 0.161 | 0.068 | 2.37x |
|  | q06 | flat | 0.164 | 0.174 | 1.06 | 0.169 | 0.077 | 2.19x |
|  | q10 | node | 0.224 | 0.231 | 1.03 | 0.231 | 0.163 | 1.42x |
|  | q10 | flat | 0.224 | 0.227 | 1.01 | 0.236 | 0.144 | 1.64x |
|  | q12 | node | 0.175 | 0.188 | 1.07 | 0.186 | 0.119 | 1.56x |
|  | q12 | flat | 0.177 | 0.183 | 1.03 | 0.185 | 0.099 | 1.87x |
| TPC-H SF10 (22 RG) | q01 | node | 3.587 | 3.501 | 0.98 | 0.613 | 0.623 | 0.98x |
|  | q01 | flat | 3.472 | 3.478 | 1.00 | 0.635 | 0.633 | 1.00x |
|  | q03 | node | 2.061 | 2.077 | 1.01 | 0.373 | 0.368 | 1.01x |
|  | q03 | flat | 2.036 | 2.050 | 1.01 | 0.376 | 0.374 | 1.01x |
|  | q04 | node | 1.663 | 1.641 | 0.99 | 0.362 | 0.351 | 1.03x |
|  | q04 | flat | 1.608 | 1.596 | 0.99 | 0.326 | 0.335 | 0.97x |
|  | q06 | node | 1.579 | 1.548 | 0.98 | 0.269 | 0.268 | 1.00x |
|  | q06 | flat | 1.532 | 1.523 | 0.99 | 0.262 | 0.266 | 0.98x |
|  | q12 | node | 1.691 | 1.662 | 0.98 | 0.434 | 0.371 | 1.17x |
|  | q12 | flat | 1.610 | 1.656 | 1.03 | 0.311 | 0.320 | 0.97x |
| XMark (1 RG) | q02 | node | 0.030 | 0.031 | 1.03 | 0.028 | 0.015 | 1.87x |
|  | q02 | flat_umbra | 0.052 | 0.054 | 1.04 | 0.056 | 0.041 | 1.37x |
|  | q02 | flat_minmax | 0.034 | 0.032 | 0.94 | 0.036 | 0.024 | 1.50x |
|  | q03 | node | 0.035 | 0.035 | 1.00 | 0.037 | 0.021 | 1.76x |
|  | q03 | flat_umbra | 0.268 | 0.263 | 0.98 | 0.237 | 0.125 | 1.90x |
|  | q03 | flat_minmax | 0.063 | 0.062 | 0.98 | 0.065 | 0.046 | 1.41x |
|  | q04 | node | 0.028 | 0.029 | 1.04 | 0.032 | 0.016 | 2.00x |
|  | q04 | flat_umbra | 0.045 | 0.043 | 0.96 | 0.030 | 0.036 | 0.83x |
|  | q04 | flat_minmax | 0.039 | 0.038 | 0.97 | 0.040 | 0.025 | 1.60x |
|  | q04p | node | 0.034 | 0.035 | 1.03 | 0.036 | 0.020 | 1.80x |
|  | q04p | flat_umbra | 0.065 | 0.066 | 1.02 | 0.053 | 0.039 | 1.36x |
|  | q04p | flat_minmax | 0.044 | 0.045 | 1.02 | 0.046 | 0.028 | 1.64x |
| DBLP (6 RG) | q06 | node | 2.544 | 2.535 | 1.00 | 0.790 | 0.607 | 1.30x |
|  | q06 | flat | 2.553 | 2.549 | 1.00 | 0.939 | 0.809 | 1.16x |
|  | q07 | node | 3.415 | 3.479 | 1.02 | 1.069 | 0.808 | 1.32x |
|  | q07 | flat | 3.463 | 3.510 | 1.01 | 1.089 | 0.801 | 1.36x |
|  | q08 | node | 1.142 | 1.146 | 1.00 | 0.321 | 0.273 | 1.18x |
|  | q08 | flat | 1.133 | 1.106 | 0.98 | 0.326 | 0.305 | 1.07x |
|  | q09 | node | 1.542 | 1.554 | 1.01 | 0.452 | 0.346 | 1.31x |
|  | q09 | flat | 1.560 | 1.539 | 0.99 | 0.457 | 0.340 | 1.34x |

- **1 thread**: new/base 0.91-1.07 for node and flat, within the noise of the unchanged builtin/split code (0.91-1.04).
- **16 threads**: TPC-H SF1 1.4-2.4x, XMark 1.4-2.0x (except Q4 flat_umbra), DBLP 1.1-1.4x faster. TPC-H SF10 has
  more row groups than threads and is not split (0.97-1.03; Q12 node 1.17x is within the 16-thread noise).
- Known regression: XMark Q4 `flat_umbra` 0.83x (30ms -> 36ms). It scans the bidders twice with a selective filter,
  so the two pre-passes over the levels cost more than the parallel scan saves. Sharing the pre-pass of a node between
  the scans of one query, or not splitting small nodes, would avoid it.
- Two fixes came out of these measurements: an earlier version also split the 22 row groups of TPC-H SF10 (SF10 Q3
  flat 0.87x), and read the levels for the pre-pass from the first projected column (a string column for XMark Q4).

## Parts at page boundaries, with the pre-pass per page (base / slot / page)

Three binaries, interleaved with 1 and 16 threads (fastest of 3 runs; CPU = user + sys of all threads, smallest of
3): `base` before the parallel scan, `slot` the parts of 122,880 slots (previous version), `page` the parts at page
boundaries with the pre-pass counted once per page. All results equal their references.

How the parts are chosen now (`ParquetNodeTaskPlan::Create`):
- The page headers of the columns that are read are read once (a directory of offset, first slot and values per page),
  and every column of a part starts at the page that holds its first slot (`ColumnReader::SeekToPage`, after loading
  the dictionary), instead of skipping the pages before it by their headers.
- About one part per thread, starting at the pages of the largest column that is read and has a page for every part
  (else the one with the most pages): its pages are decompressed once, the other columns at most one page more per
  part.
- The rows before a part are counted per page, in parallel, in the cheapest column of the node that has a page for
  every part, plus the start of the page a part starts in. The pages and their counts are kept for the query
  (`ClientContextState`), so the parts and all scans of the same column chunk in a query share them.
- With 1 thread, or row groups that are not split, the scan is the one from before. Page counts per column of these
  files: TPC-H SF1 lineitems 2-174 (l_linestatus 2, l_shipdate 10, l_extendedprice 46), orders 1-73, XMark bidders 1-8.

Seconds, base / slot / page (wall: fastest run; CPU: user + sys of all threads):

| dataset | query | variant | wall t1 | CPU t1 | wall t16 | CPU t16 |
|---|---|---|---|---|---|---|
| TPC-H SF1 (1 RG) | q01 | node | 0.451 / 0.347 / 0.343 | 0.45 / 0.35 / 0.35 | 0.355 / 0.151 / **0.094** | 0.36 / 2.11 / 1.26 |
|  | q01 | flat | 0.367 / 0.360 / 0.347 | 0.37 / 0.36 / 0.35 | 0.352 / 0.154 / **0.087** | 0.35 / 2.23 / 1.15 |
|  | q03 | node | 0.293 / 0.248 / 0.291 | 0.29 / 0.25 / 0.30 | 0.238 / 0.140 / **0.107** | 0.24 / 1.80 / 1.03 |
|  | q03 | flat | 0.235 / 0.242 / 0.293 | 0.23 / 0.25 / 0.30 | 0.238 / 0.133 / **0.108** | 0.24 / 1.67 / 0.99 |
|  | q04 | node | 0.184 / 0.219 / 0.234 | 0.18 / 0.22 / 0.24 | 0.182 / 0.158 / **0.089** | 0.23 / 1.96 / 0.60 |
|  | q04 | flat | 0.254 / 0.266 / 0.220 | 0.25 / 0.27 / 0.22 | 0.257 / 0.104 / **0.064** | 0.32 / 1.34 / 0.50 |
|  | q06 | node | 0.182 / 0.206 / 0.165 | 0.18 / 0.21 / 0.17 | 0.202 / 0.067 / **0.041** | 0.22 / 0.96 / 0.50 |
|  | q06 | flat | 0.169 / 0.162 / 0.190 | 0.17 / 0.17 / 0.19 | 0.200 / 0.072 / **0.063** | 0.20 / 0.98 / 0.53 |
|  | q10 | node | 0.233 / 0.292 / 0.236 | 0.23 / 0.29 / 0.24 | 0.286 / 0.141 / **0.170** | 0.32 / 1.53 / 1.06 |
|  | q10 | flat | 0.273 / 0.224 / 0.274 | 0.28 / 0.22 / 0.27 | 0.287 / 0.146 / **0.143** | 0.30 / 1.54 / 0.85 |
|  | q12 | node | 0.188 / 0.191 / 0.196 | 0.19 / 0.19 / 0.20 | 0.191 / 0.112 / **0.087** | 0.19 / 1.35 / 0.38 |
|  | q12 | flat | 0.246 / 0.202 / 0.218 | 0.25 / 0.21 / 0.22 | 0.237 / 0.150 / **0.102** | 0.24 / 1.79 / 0.45 |
| XMark (1 RG) | q02 | node | 0.047 / 0.048 / 0.045 | 0.05 / 0.05 / 0.05 | 0.045 / 0.030 / **0.041** | 0.10 / 0.13 / 0.06 |
|  | q02 | flat_minmax | 0.052 / 0.063 / 0.052 | 0.05 / 0.06 / 0.05 | 0.057 / 0.052 / **0.057** | 0.06 / 0.13 / 0.08 |
|  | q02 | flat_umbra | 0.083 / 0.086 / 0.085 | 0.08 / 0.09 / 0.08 | 0.102 / 0.082 / **0.092** | 0.12 / 0.21 / 0.15 |
|  | q03 | node | 0.057 / 0.060 / 0.057 | 0.06 / 0.06 / 0.06 | 0.064 / 0.042 / **0.067** | 0.08 / 0.13 / 0.08 |
|  | q03 | flat_minmax | 0.097 / 0.102 / 0.100 | 0.10 / 0.10 / 0.10 | 0.112 / 0.090 / **0.124** | 0.13 / 0.21 / 0.14 |
|  | q03 | flat_umbra | 0.508 / 0.516 / 0.507 | 0.51 / 0.52 / 0.50 | 0.396 / 0.210 / **0.406** | 0.69 / 0.89 / 0.87 |
|  | q04 | node | 0.048 / 0.060 / 0.049 | 0.05 / 0.06 / 0.05 | 0.062 / 0.037 / **0.048** | 0.07 / 0.14 / 0.16 |
|  | q04 | flat_minmax | 0.068 / 0.059 / 0.052 | 0.07 / 0.06 / 0.05 | 0.064 / 0.056 / **0.048** | 0.08 / 0.18 / 0.13 |
|  | q04 | flat_umbra | 0.075 / 0.073 / 0.073 | 0.07 / 0.07 / 0.07 | 0.056 / 0.062 / **0.064** | 0.10 / 0.22 / 0.19 |
|  | q04p | node | 0.060 / 0.064 / 0.052 | 0.06 / 0.06 / 0.05 | 0.067 / 0.041 / **0.051** | 0.08 / 0.14 / 0.17 |
|  | q04p | flat_minmax | 0.070 / 0.072 / 0.067 | 0.07 / 0.07 / 0.07 | 0.075 / 0.062 / **0.059** | 0.09 / 0.18 / 0.15 |
|  | q04p | flat_umbra | 0.100 / 0.106 / 0.096 | 0.10 / 0.11 / 0.10 | 0.087 / 0.084 / **0.065** | 0.13 / 0.29 / 0.21 |
| DBLP (6 RG) | q06 | node | 2.987 / 2.993 / 3.194 | 2.98 / 2.99 / 3.18 | 1.192 / 0.959 / **1.062** | 6.60 / 13.29 / 14.20 |
|  | q06 | flat | 2.695 / 2.798 / 2.653 | 2.69 / 2.79 / 2.65 | 1.112 / 0.921 / **0.983** | 6.27 / 12.59 / 13.06 |
|  | q07 | node | 3.721 / 3.631 / 3.739 | 3.72 / 3.62 / 3.73 | 1.407 / 1.112 / **0.917** | 7.70 / 14.15 / 11.53 |
|  | q07 | flat | 3.654 / 4.129 / 4.056 | 3.65 / 4.12 / 4.05 | 1.073 / 1.027 / **0.807** | 6.87 / 12.59 / 10.63 |
|  | q08 | node | 1.141 / 1.160 / 1.128 | 1.14 / 1.16 / 1.13 | 0.378 / 0.341 / **0.378** | 1.51 / 4.56 / 4.90 |
|  | q08 | flat | 1.175 / 1.164 / 1.171 | 1.17 / 1.16 / 1.17 | 0.387 / 0.385 / **0.384** | 1.77 / 5.41 / 4.99 |
|  | q09 | node | 1.566 / 1.567 / 1.593 | 1.56 / 1.57 / 1.59 | 0.588 / 0.441 / **0.497** | 2.49 / 5.98 / 6.59 |
|  | q09 | flat | 1.570 / 1.572 / 1.599 | 1.57 / 1.57 / 1.60 | 0.527 / 0.444 / **0.529** | 2.23 / 5.83 / 7.18 |
| TPC-H SF10 (22 RG) | q01 | node | 3.576 / 3.679 / 3.499 | 3.57 / 3.67 / 3.50 | 0.626 / 0.668 / **0.950** | 7.32 / 7.88 / 11.32 |
|  | q01 | flat | 3.459 / 3.517 / 3.503 | 3.45 / 3.51 / 3.50 | 0.902 / 0.870 / **0.866** | 10.40 / 10.07 / 10.05 |
|  | q03 | node | 2.272 / 2.028 / 2.022 | 2.27 / 2.02 / 2.02 | 0.407 / 0.401 / **0.408** | 4.95 / 4.69 / 4.91 |
|  | q03 | flat | 2.013 / 1.989 / 2.091 | 2.01 / 1.98 / 2.09 | 0.375 / 0.365 / **0.381** | 4.33 / 4.48 / 4.58 |
|  | q04 | node | 1.616 / 1.607 / 1.603 | 1.61 / 1.60 / 1.60 | 0.318 / 0.329 / **0.325** | 3.35 / 3.70 / 3.55 |
|  | q04 | flat | 1.605 / 1.650 / 1.610 | 1.60 / 1.65 / 1.61 | 0.327 / 0.322 / **0.314** | 3.30 / 3.49 / 3.51 |
|  | q06 | node | 1.523 / 1.537 / 1.521 | 1.52 / 1.54 / 1.52 | 0.328 / 0.277 / **0.267** | 3.84 / 2.99 / 3.21 |
|  | q06 | flat | 1.735 / 1.687 / 1.617 | 1.73 / 1.68 / 1.62 | 0.260 / 0.250 / **0.260** | 3.02 / 3.00 / 3.00 |
|  | q12 | node | 1.727 / 1.714 / 1.700 | 1.72 / 1.71 / 1.70 | 0.430 / 0.380 / **0.414** | 5.07 / 4.29 / 4.77 |
|  | q12 | flat | 1.684 / 1.721 / 1.661 | 1.68 / 1.72 / 1.66 | 0.379 / 0.380 / **0.383** | 4.22 / 4.20 / 3.93 |

With 1 thread, page/base (the scan of 1 thread is unchanged; builtin/split in the same run show the noise):

| dataset | node/flat wall | node/flat CPU | builtin/split wall (unchanged code) |
|---|---|---|---|
| TPC-H SF1 (1 RG) | 0.76-1.27 | 0.76-1.30 | 0.76-1.25 |
| XMark (1 RG) | 0.76-1.03 | 0.77-1.03 | 0.74-1.05 |
| DBLP (6 RG) | 0.98-1.11 | 0.98-1.11 | 0.89-1.05 |
| TPC-H SF10 (22 RG) | 0.89-1.04 | 0.89-1.04 | 0.82-1.14 |

- **TPC-H SF1, 16 threads**: page is the fastest for all queries but Q10 node (0.170s vs slot 0.141s; flat Q10 equal),
  and uses 31-75% less CPU than slot - e.g. Q4 node 0.089s (slot 0.158s, base 0.182s), Q12 node CPU 0.38s (slot
  1.35s). From 1 to 16 threads SF1 now gets 1.4-4.0x (slot 1.3-3.1x, base 0.8-1.3x); Q10 node is the lowest.
- **XMark**: page is slower than slot - the columns of the bidders have 1-8 pages, so there are few parts or none
  (`increase` has one page). The queries take 30-70 ms.
- **DBLP**: Q7 is faster (node 0.917s vs slot 1.112s), Q6/Q9 node are between base and slot and Q8 node equals base;
  the flat variants are equal to slot or faster. Its CPU with 16 threads is about twice the CPU with 1 thread for all
  binaries, like TPC-H SF10 (the cost of 16 hardware threads).
- **TPC-H SF10** (more row groups than threads, not split by any binary): equal within the noise; Q1 node at 16
  threads measured 0.95s once, and 0.55-0.68s for all binaries in three repetitions of 10 runs.

## Why 16 threads gave only ~2x on the files with a single row group (slot version)

Measured with `profile_breakdown.py` (perf samples of all threads, mapped to functions with `nm`; this perf has no
call stacks) and the operator timings of `EXPLAIN ANALYZE` (CPU summed over threads, without the pre-pass, which runs
when the scan is initialized). Node variants, `new` binary.

| query | wall t1 | wall t16 | speedup | CPU t1 | CPU t16 | CPU x | Parquet decode t1/t16 | of which snappy | levels/skip | keys | join | aggregate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SF1 Q1 | 343 | 142 | 2.4x | 334 | 1834 | 5.5 | 136/896 | 50/577 | 0/199 | 36/82 | 0/0 | 47/113 |
| SF1 Q3 | 236 | 115 | 2.1x | 229 | 1345 | 5.9 | 109/771 | 60/535 | 0/134 | 49/88 | 19/40 | 2/7 |
| SF1 Q4 | 171 | 89 | 1.9x | 164 | 958 | 5.8 | 51/426 | 15/252 | 0/118 | 48/96 | 17/34 | 5/18 |
| SF1 Q6 | 158 | 60 | 2.6x | 152 | 752 | 4.9 | 79/426 | 41/293 | 0/43 | 42/81 | 0/0 | 0/0 |
| SF1 Q10 | 223 | 141 | 1.6x | 215 | 1326 | 6.2 | 97/712 | 52/482 | 0/178 | 49/98 | 13/19 | 6/18 |
| SF1 Q12 | 179 | 98 | 1.8x | 176 | 1192 | 6.8 | 60/534 | 10/305 | 0/154 | 48/96 | 11/18 | 1/2 |
| XMark Q2 | 31 | 15 | 2.1x | 31 | 59 | 1.9 | 4/8 | 0/2 | 0/2 | 3/4 | 2/4 | 6/14 |
| XMark Q3 | 38 | 23 | 1.7x | 38 | 66 | 1.7 | 4/8 | 0/2 | 0/1 | 3/5 | 0/0 | 10/16 |
| XMark Q4 | 30 | 17 | 1.8x | 29 | 53 | 1.8 | 10/22 | 5/11 | 0/1 | 4/3 | 0/0 | 5/8 |
| SF10 Q4 (22 RG, not split) | 1671 | 322 | 5.2x | 1626 | 3502 | 2.2 | 441/754 | 0/0 | 0/1 | 402/846 | 233/450 | 68/146 |

(milliseconds; one profiled run each, so the speedups differ slightly from the benchmark tables)

- **The CPU time of the split scans grows 5-7x from 1 to 16 threads** (TPC-H SF10, which is not split: 2.2x - the
  cost of 16 hardware threads on 4 performance + 8 efficiency cores with SMT). Keys, joins and aggregates grow ~2x like
  SF10; Parquet decoding grows 6-10x, snappy decompression 10-30x, and level decoding/skipping appears (0 -> 43-199ms).
  EXPLAIN ANALYZE shows the same: SF1 Q1 table scan 208ms -> 1852ms CPU, its aggregate 73 -> 188ms.
- Cause: a part of a row group starts with `Skip(start)`. Pages before it are skipped by their header, but the page that
  contains the start is decompressed completely and its levels are decoded up to the start - for every column of every
  part. The parts (122,880 slots) are about as large as or smaller than the pages (e.g. `l_shipdate`: 11.6 MB
  uncompressed for 6M values), so the same pages are decompressed again and again. Q1 and Q6 do not need ancestor keys,
  have no pre-pass, and are affected just as much.
- Larger parts trade parallelism for less repeated work (16 threads, fastest of 5, seconds (CPU)):

  | parts of (slots) | 122,880 (default) | 250K | 500K | 1M | 2M | not split |
  |---|---|---|---|---|---|---|
  | SF1 Q1 | 0.136 (1.98) | 0.100 (1.27) | 0.086 (1.02) | 0.101 (0.65) | 0.110 (0.42) | 0.337 (0.34) |
  | SF1 Q4 | 0.082 (1.04) | 0.071 (0.68) | 0.060 (0.49) | 0.073 (0.31) | 0.096 (0.25) | 0.175 (0.18) |
  | SF1 Q6 | 0.060 (0.86) | 0.046 (0.56) | 0.040 (0.44) | 0.045 (0.26) | 0.053 (0.20) | 0.162 (0.16) |

  Even the best size uses 3x the CPU of a single scan; parts that start at page boundaries would avoid most of it.
- **The pre-pass** is a phase of its own: SF1 Q4 at 16 threads (89 ms) spends ~25 ms scanning orders and building the
  hash table (5-10 busy threads), ~25 ms in the pre-pass of the lineitems (15 threads, mostly decompressing the pages
  of the levels - also repeatedly), ~35 ms in the probe pipeline and ~4 ms in the final aggregate. Q12: ~25 of 98 ms.
- **XMark**: only 30-60 ms of CPU in total; its bidder node (609K slots) gives 5 parts and the auctions (120K) one, so
  2-4 threads are busy; the grouped first()/last() aggregates are a large share.
- **Filters**: in these queries they keep most rows of the large nodes (SF1 Q4: 63% of the lineitems, Q1: 99%); the
  selective ones are on small nodes (Q4: 3.8% of the orders, 35 ms of CPU with one thread).

## XMark: element order

The XMark queries need the order of the bidders of an auction. Umbra exposes a surrogate key per node (`"...bidder.sk"`);
`read_parquet_flat` now exposes the same as `"<path>._sk"` (the row number of the node in the file, in element order).

- **Q2, NULL rows**: the builtin query returns a row for every auction (120,000), with NULL for the 11,586 auctions
  without bidders (`bidder[1]` of an empty list). `read_parquet_flat` joins the nodes with inner joins, so these
  auctions have no row. The flat variants are compared with `q02.flat_*.oracle`: the builtin query without the NULL
  rows (108,414 rows). The node variant keeps the NULL rows with a LEFT JOIN and is compared with the builtin query.
- **Q3**: auctions without bidders have no first/last increase in any variant - all compare with the builtin query.
- **Q4**: the builtin query returns an auction once when the first bid of person20 is before the first bid of
  person51; Umbra's (and the split) query returns every pair of such bids. `flat_minmax` and `node` have the builtin
  semantics; `flat_umbra` and `split` are compared with `q04.flat_umbra.oracle` / `q04.split.oracle` (every pair of
  positions, from the nested lists).
- **q04p**: person20 and person51 never bid in the same auction, so Q4 returns no rows and checks nothing. q04p is Q4
  with person148112 and person189013, who bid in 41 common auctions.
- Correlated subqueries (`flat_umbra`) vs a join with the min/max key per parent (`flat_minmax`), 16 threads: the join
  is faster for all queries - Q2 0.024s vs 0.041s, Q3 (first and last bidder) 0.046s vs 0.125s, Q4 0.025s vs 0.036s,
  Q4p 0.028s vs 0.039s. With 1 thread Q3 shows the largest difference (0.062s vs 0.263s).

## Notes

- XMark node vs split (Q3 ~0.1x, Q2 ~0.3x): caused by the query formulation, not by the files. The repository's split
  queries find the first/last bidder with correlated subqueries (min/max `_sk` per auction `_id`), which DuckDB plans as
  CTEs with three scans of the bidders and several joins over ~1.8M intermediate rows. The node queries take
  `first()`/`last()` per `_ak1` group. With that formulation on the split files: Q2 split 0.021s vs node 0.032s, Q3 split
  0.035s vs node 0.042s (node/split 1.5x and 1.2x, in line with the other datasets; measured before the parallel scan).
- XMark Q4 builtin: the repository's `x -> ...` lambdas were rewritten to `lambda x: ...` (arrow lambdas are disabled
  in this build); semantics unchanged.
- A bug found by these runs and fixed: a top-level column chunk with only NULL values (DBLP `year`, row group 4) is
  skipped by the column reader without advancing its count of remaining values -> hang / TProtocolException.
