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
boundaries - or within pages - with the pre-pass counted once per page. All results equal their references.

How the parts are chosen now (`ParquetNodeTaskPlan::Create`):
- The page headers of the columns that are read are read once (a directory of offset, first slot and values per page),
  and every column of a part starts at the page that holds its first slot (`ColumnReader::SeekToPage`, after loading
  the dictionary), then skips to the slot within the page - the paper's "offset" (Listing 3, lines 7-8).
- About one part per thread (at least `parquet_node_task_slots` slots each). The parts start at the pages of the
  largest column that is read and has a page for every part - its pages are decompressed once, the other columns at
  most one page more per part. When no column that is read has that many pages, the parts start at offsets within
  the pages of the one with the most pages, which are then decompressed by more than one part.
- The rows before a part are counted per page, in parallel, in the cheapest column of the node that has a page for
  every part (or else the column of the boundaries), plus the slots of the page a part starts in up to its offset. The
  pages and their counts are kept for the query (`ClientContextState`), so the parts and all scans of the same column
  chunk in a query share them.
- With 1 thread, or row groups that are not split, the scan is the one from before. Page counts per column of these
  files: TPC-H SF1 lineitems 2-174 (l_linestatus 2, l_shipdate 10, l_extendedprice 46), orders 1-73, XMark bidders 1-8.
- An earlier version chose the column with the fewest pages for the boundaries (l_linestatus: 2 parts) and the
  cheapest column for counting (2 pages, counted by 2 threads); it was slower than slot for the joins.

Seconds, base / slot / page (wall: fastest run; CPU: user + sys of all threads):

| dataset | query | variant | wall t1 | CPU t1 | wall t16 | CPU t16 |
|---|---|---|---|---|---|---|
| TPC-H SF1 (1 RG) | q01 | node | 0.372 / 0.360 / 0.366 | 0.39 / 0.36 / 0.37 | 0.379 / 0.199 / **0.115** | 0.38 / 2.62 / 1.27 |
|  | q01 | flat | 0.359 / 0.349 / 0.359 | 0.36 / 0.35 / 0.36 | 0.375 / 0.188 / **0.102** | 0.38 / 2.22 / 1.11 |
|  | q03 | node | 0.234 / 0.242 / 0.233 | 0.23 / 0.25 / 0.23 | 0.242 / 0.153 / **0.107** | 0.24 / 1.86 / 1.03 |
|  | q03 | flat | 0.248 / 0.236 / 0.241 | 0.25 / 0.24 / 0.24 | 0.243 / 0.152 / **0.105** | 0.24 / 1.64 / 0.96 |
|  | q04 | node | 0.183 / 0.177 / 0.206 | 0.18 / 0.18 / 0.21 | 0.176 / 0.099 / **0.077** | 0.19 / 1.28 / 0.84 |
|  | q04 | flat | 0.220 / 0.170 / 0.174 | 0.22 / 0.17 / 0.18 | 0.175 / 0.089 / **0.067** | 0.18 / 1.09 / 0.77 |
|  | q06 | node | 0.166 / 0.198 / 0.199 | 0.17 / 0.20 / 0.20 | 0.176 / 0.069 / **0.057** | 0.18 / 0.98 / 0.66 |
|  | q06 | flat | 0.204 / 0.198 / 0.192 | 0.20 / 0.20 / 0.20 | 0.197 / 0.079 / **0.054** | 0.20 / 1.11 / 0.57 |
|  | q10 | node | 0.270 / 0.220 / 0.229 | 0.27 / 0.22 / 0.23 | 0.234 / 0.161 / **0.152** | 0.27 / 1.68 / 1.02 |
|  | q10 | flat | 0.233 / 0.273 / 0.282 | 0.23 / 0.27 / 0.28 | 0.226 / 0.160 / **0.152** | 0.25 / 1.58 / 1.01 |
|  | q12 | node | 0.180 / 0.208 / 0.210 | 0.18 / 0.21 / 0.21 | 0.201 / 0.142 / **0.091** | 0.21 / 1.75 / 0.99 |
|  | q12 | flat | 0.192 / 0.191 / 0.194 | 0.20 / 0.19 / 0.19 | 0.187 / 0.124 / **0.072** | 0.20 / 1.51 / 0.82 |
| XMark (1 RG) | q02 | node | 0.032 / 0.032 / 0.032 | 0.03 / 0.03 / 0.03 | 0.027 / 0.015 / **0.021** | 0.04 / 0.06 / 0.10 |
|  | q02 | flat_minmax | 0.033 / 0.034 / 0.034 | 0.03 / 0.03 / 0.03 | 0.038 / 0.029 / **0.034** | 0.05 / 0.07 / 0.10 |
|  | q02 | flat_umbra | 0.053 / 0.055 / 0.052 | 0.05 / 0.05 / 0.05 | 0.063 / 0.043 / **0.051** | 0.08 / 0.11 / 0.14 |
|  | q03 | node | 0.039 / 0.038 / 0.035 | 0.04 / 0.04 / 0.04 | 0.043 / 0.021 / **0.028** | 0.06 / 0.07 / 0.10 |
|  | q03 | flat_minmax | 0.072 / 0.066 / 0.067 | 0.07 / 0.07 / 0.07 | 0.067 / 0.050 / **0.056** | 0.08 / 0.12 / 0.15 |
|  | q03 | flat_umbra | 0.307 / 0.303 / 0.311 | 0.31 / 0.30 / 0.32 | 0.269 / 0.136 / **0.132** | 0.42 / 0.53 / 0.53 |
|  | q04 | node | 0.030 / 0.030 / 0.030 | 0.03 / 0.03 / 0.03 | 0.032 / 0.020 / **0.023** | 0.04 / 0.08 / 0.08 |
|  | q04 | flat_minmax | 0.038 / 0.040 / 0.039 | 0.04 / 0.04 / 0.04 | 0.041 / 0.026 / **0.033** | 0.05 / 0.08 / 0.10 |
|  | q04 | flat_umbra | 0.045 / 0.047 / 0.046 | 0.05 / 0.05 / 0.05 | 0.030 / 0.041 / **0.041** | 0.05 / 0.13 / 0.13 |
|  | q04p | node | 0.036 / 0.036 / 0.038 | 0.04 / 0.04 / 0.04 | 0.037 / 0.019 / **0.027** | 0.04 / 0.08 / 0.10 |
|  | q04p | flat_minmax | 0.047 / 0.045 / 0.046 | 0.05 / 0.04 / 0.05 | 0.049 / 0.029 / **0.035** | 0.05 / 0.09 / 0.10 |
|  | q04p | flat_umbra | 0.066 / 0.067 / 0.072 | 0.07 / 0.07 / 0.07 | 0.053 / 0.043 / **0.043** | 0.08 / 0.13 / 0.13 |
| DBLP (6 RG) | q06 | node | 2.759 / 2.537 / 2.519 | 2.75 / 2.53 / 2.51 | 1.053 / 0.757 / **0.813** | 5.70 / 10.24 / 10.99 |
|  | q06 | flat | 2.622 / 2.553 / 2.622 | 2.62 / 2.55 / 2.62 | 1.022 / 0.791 / **0.871** | 5.46 / 10.64 / 11.20 |
|  | q07 | node | 3.421 / 3.602 / 3.408 | 3.42 / 3.59 / 3.40 | 1.229 / 1.021 / **1.103** | 6.88 / 13.36 / 14.39 |
|  | q07 | flat | 3.713 / 3.506 / 3.436 | 3.70 / 3.50 / 3.43 | 1.290 / 1.078 / **1.053** | 7.60 / 14.73 / 13.65 |
|  | q08 | node | 1.140 / 1.131 / 1.134 | 1.14 / 1.13 / 1.13 | 0.403 / 0.323 / **0.380** | 1.75 / 4.35 / 5.03 |
|  | q08 | flat | 1.126 / 1.111 / 1.144 | 1.12 / 1.11 / 1.14 | 0.375 / 0.336 / **0.393** | 1.73 / 4.53 / 5.34 |
|  | q09 | node | 1.530 / 1.552 / 1.558 | 1.53 / 1.55 / 1.56 | 0.511 / 0.384 / **0.392** | 2.11 / 4.99 / 5.17 |
|  | q09 | flat | 1.552 / 1.565 / 1.560 | 1.55 / 1.57 / 1.56 | 0.469 / 0.347 / **0.377** | 2.14 / 4.73 / 5.03 |
| TPC-H SF10 (22 RG) | q01 | node | 3.540 / 3.571 / 3.485 | 3.53 / 3.57 / 3.48 | 0.756 / 0.744 / **0.752** | 8.89 / 8.64 / 8.35 |
|  | q01 | flat | 3.493 / 3.526 / 3.502 | 3.49 / 3.53 / 3.50 | 0.869 / 0.865 / **0.858** | 10.03 / 10.07 / 9.97 |
|  | q03 | node | 2.069 / 2.119 / 2.027 | 2.06 / 2.11 / 2.02 | 0.486 / 0.467 / **0.453** | 5.79 / 5.35 / 5.11 |
|  | q03 | flat | 2.132 / 2.284 / 2.017 | 2.13 / 2.28 / 2.02 | 0.620 / 0.510 / **0.394** | 7.59 / 5.86 / 4.53 |
|  | q04 | node | 1.696 / 1.672 / 1.660 | 1.70 / 1.67 / 1.66 | 0.377 / 0.403 / **0.406** | 4.04 / 4.32 / 4.59 |
|  | q04 | flat | 1.622 / 1.643 / 1.570 | 1.62 / 1.64 / 1.57 | 0.373 / 0.370 / **0.333** | 4.02 / 3.70 / 3.47 |
|  | q06 | node | 1.552 / 1.566 / 1.551 | 1.55 / 1.56 / 1.55 | 0.259 / 0.260 / **0.269** | 3.00 / 3.05 / 3.00 |
|  | q06 | flat | 1.549 / 1.578 / 1.529 | 1.55 / 1.58 / 1.53 | 0.262 / 0.265 / **0.258** | 2.99 / 2.90 / 2.87 |
|  | q12 | node | 1.659 / 1.643 / 1.666 | 1.66 / 1.64 / 1.67 | 0.311 / 0.303 / **0.300** | 3.56 / 3.52 / 3.46 |
|  | q12 | flat | 1.638 / 1.629 / 1.637 | 1.64 / 1.63 / 1.64 | 0.316 / 0.296 / **0.309** | 3.52 / 3.44 / 3.49 |

With 1 thread, page/base (the scan of 1 thread is unchanged; builtin/split in the same run show the noise):

| dataset | node/flat wall | node/flat CPU | builtin/split wall (unchanged code) |
|---|---|---|---|
| TPC-H SF1 (1 RG) | 0.79-1.21 | 0.79-1.22 | 0.76-1.04 |
| XMark (1 RG) | 0.90-1.09 | 0.90-1.09 | 0.97-1.08 |
| DBLP (6 RG) | 0.91-1.02 | 0.91-1.02 | 0.98-1.05 |
| TPC-H SF10 (22 RG) | 0.95-1.00 | 0.95-1.00 | 0.78-1.06 |

- **TPC-H SF1, 16 threads**: page is the fastest for all queries (Q10 node 0.152s, slot 0.161s, base 0.234s), with
  29-51% less CPU than slot. From 1 to 16 threads SF1 now gets 1.5-3.6x (slot 1.4-2.9x).
- **XMark**: faster than base and than the version that did not split within pages, but slower than slot by a few
  milliseconds: its bidder columns have 1-8 pages, so the parts start within pages that every part decompresses
  (CPU 0.10s vs slot 0.06s for Q2), and the queries take 20-50 ms.
- **DBLP** (6 row groups, author lists with ~50 pages per row group): equal to slot within 10%, except Q8 (0.380s
  vs slot 0.323s for node, 17% slower); faster than base for all queries.
- **TPC-H SF10** (more row groups than threads, not split by any binary): equal within the noise.

**Limitation: columns with few pages.** A page is decompressed as a whole, by every part that reads from it. When the
columns that are read have fewer pages than threads (XMark bidders: 1-8 pages for 609K slots; parquet-cpp-arrow
writes pages of about 1 MB, and a compact column - dictionary encoded, few distinct values - holds millions of values
in one page), the parts start within pages, and each of these pages is decompressed by all the parts that start in or
cross it: more threads only add CPU, not throughput, for these columns (XMark Q2 node: CPU 0.10s vs slot 0.06s). The
minimum part size (`parquet_node_task_slots`, 122,880 slots) stays: lower values would give XMark more parts but
decompress the same pages more often. Avoiding it would need the decompressed pages to be shared between the parts
(read once, used by several threads), or files with smaller pages; the page index (`OffsetIndex`) does not help, as it
only locates pages.

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

## Filter pushdown into read_parquet_node (phase 1)

`read_parquet_node` now accepts filters (`filter_pushdown`, generic expressions via `pushdown_expression`), which
`read_parquet_flat` passes on to the scans of its nodes:

- **Evaluation in the scan**: after the keys of a batch are generated, the filters are evaluated on the rows of the
  node (keys first, then the columns they use). The other columns are decoded only for the slots of the rows that
  pass (`ColumnReader::Select`). The column readers' own `Filter`/`DirectFilter` are not used: they skip pages without
  reading their levels, which the keys need. Placeholders (`include_empty`) are NULL rows and are filtered as such.
- **Skipping tasks** (a row group, or a part of one with several threads): a task is skipped when a filter on a key
  excludes the key range of its rows, or a filter on a column excludes the statistics of the column chunk of its row
  group (FLOAT/DOUBLE are not checked - NaN is not within min/max). The debug log reports
  `the filters of the query skip N of M tasks of node "..."`.
- **Filters that joins create while the query runs** (min/max, IN, PRF of the hash join's build side): used only with
  `SET parquet_node_join_filter_pruning = true` (default false), for skipping tasks and evaluating rows; the log then
  adds `, the filters of joins N more`. Using join information to skip parts of the probe side is sideways information
  passing, which the paper only names as future work (Section 6.5) - **this setting and the `join` configuration below
  are additions beyond the paper's scope.** With the setting off, these filters are ignored (the joins apply them
  anyway, so results are the same).
- Scope: phase 1 only. Skipping at page granularity (phase 2) and with page statistics (phase 3) are not implemented.

**Page index in the paper's datasets** (checked in the footers with pyarrow): ColumnIndex/OffsetIndex (page statistics)
are present in every column chunk only in the parquet-mr files - TPC-H SF10, nested and normalized. The
parquet-cpp-arrow files (TPC-H SF1, XMark, DBLP, synthetic) have none. All files have column chunk statistics.

### Selectivity experiment (counterpart of the paper's Fig. 15)

Running:
```
python3 make_selectivity_queries.py                                     # queries/selectivity_random, selectivity_sorted
mkdir <dir>/selectivity_random && ln -s <datasets dir>/synthetic/l1.parquet <dir>/selectivity_random/
python3 split_selectivity_data.py <dir>/selectivity_random/l1.parquet <dir>/selectivity_random   # pyarrow 26
python3 generate_selectivity_data.py <dir>/selectivity_sorted           # data of experiment (B), pyarrow 26
CFG="page=<page duckdb>,query=<duckdb>;SET disabled_optimizers = 'join_filter_pushdown';SET parquet_node_join_filter_pruning = false,join=<duckdb>;SET parquet_node_join_filter_pruning = true"
RUNS=5 THREADS=1,16 SKIPS=1 python3 run_bench.py "$CFG" queries/selectivity_random <dir>/selectivity_random selectivity_random.csv
RUNS=5 THREADS=1,16 SKIPS=1 python3 run_bench.py "$CFG" queries/selectivity_sorted <dir>/selectivity_sorted selectivity_sorted.csv
```

- **(A)** the paper's `synthetic/l1.parquet` (1M rows, `a` random BIGINT, a list `b` of 10 BIGINTs, one row group of
  10M slots) with the paper's predicate `a % N = 0`, N = 1 ... 10^6 (N = 1 without predicate): the selected rows are
  spread over the whole file. Every variant computes `avg(greatest(a, b))` over the elements of the selected rows.
- `split` reads pre-split files cut from the same nested file (`split_selectivity_data.py`): `normalized/l1_0.parquet`
  (`a`, `_sk`, 1 row group) and `l1_1.parquet` (`b`, `_psk0`, `_sk`, 10 row groups of 1M), with 1-based INT32 keys
  like the paper's files. The paper's own pre-split files hold *other random values* than its `l1.parquet` (other
  sums, no row matches), so they cannot be checked against the nested variants; the files cut from `l1.parquet` have
  the same layout and size (12.85 MB / 135.9 MB vs 12.87 MB / 136.2 MB) and give the same results as the nested
  variants.
- **(B) - an additional experiment beyond the paper's scope**: the same shape with `a` ascending (a = row number,
  `generate_selectivity_data.py`, which writes the pre-split files with the same code) and the range predicate
  `a < 10^6 / N`: the selected rows, and so their keys, are contiguous - the case where the join's min/max filters can
  skip parts of the child.
- Variants: `builtin` (unnest), `node` (`read_parquet_node` + join on `_ak0 = _sk`), `flat` (`read_parquet_flat`),
  `split`. **All variants return the same result in all configurations and at both thread counts**, `split` included.

**How the configurations were aligned.** Three configurations, interleaved for every query and variant, with
threads = 1 and 16:

| configuration | binary | setup SQL |
|---|---|---|
| `page` | before filter pushdown (page-aligned parallel scan) | - |
| `query` | filter pushdown | `SET disabled_optimizers = 'join_filter_pushdown'; SET parquet_node_join_filter_pruning = false;` |
| `join` (beyond the paper's scope) | filter pushdown | `SET parquet_node_join_filter_pruning = true;` |

`split` reads the pre-split files with `read_parquet`, which uses the joins' filters by default (it skips row groups by
the min/max of `_psk0` and filters rows with them). To compare like with like, the setup SQL of a configuration applies
to *every* variant: in `query` no variant gets information from the joins - the join filter pushdown optimizer is
disabled, so `split` does not use it either and no join spends time building such filters - and in `join` all
variants use it (`split` as DuckDB does by default, `node`/`flat` through the setting). `split` is therefore reported
in `query` and `join`; `builtin` has no join and is unaffected. The setup SQL is recorded in the `setup_<config>`
columns of the CSV.

Columns marked † belong to the `join` configuration. "skipped" is `<by the query's filters>+<by join filters>/<tasks>`
of the node variant, summed over its two scans (parent and child). Fastest of 5 runs; no other process used the CPU
during the runs (`busy_cpu` 0).

(A) paper data, `a % N = 0`, threads=1: wall seconds (CPU seconds)

| N | builtin | node page | node query | node join† | skipped q+j/tasks† | flat query | flat join† | split query | split join† |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.115 (0.12) | 0.153 (0.15) | 0.152 (0.15) | 0.164 (0.16) | 0+0/1 | 0.153 (0.15) | 0.165 (0.17) | 0.130 (0.13) | 0.138 (0.14) |
| 10^1 | 0.078 (0.08) | 0.095 (0.09) | 0.097 (0.10) | 0.104 (0.10) | 0+0/2 | 0.097 (0.10) | 0.104 (0.10) | 0.067 (0.07) | 0.068 (0.07) |
| 10^2 | 0.073 (0.07) | 0.085 (0.08) | 0.087 (0.09) | 0.092 (0.09) | 0+0/2 | 0.087 (0.09) | 0.091 (0.09) | 0.058 (0.06) | 0.056 (0.05) |
| 10^3 | 0.068 (0.07) | 0.085 (0.08) | 0.088 (0.09) | 0.084 (0.08) | 0+0/2 | 0.087 (0.09) | 0.096 (0.10) | 0.057 (0.06) | 0.049 (0.05) |
| 10^4 | 0.061 (0.06) | 0.090 (0.09) | 0.089 (0.09) | 0.091 (0.09) | 0+0/2 | 0.091 (0.09) | 0.093 (0.09) | 0.066 (0.07) | 0.043 (0.04) |
| 10^5 | 0.073 (0.07) | 0.088 (0.09) | 0.096 (0.10) | 0.090 (0.09) | 0+0/2 | 0.088 (0.09) | 0.090 (0.09) | 0.058 (0.06) | 0.039 (0.04) |
| 10^6 | 0.043 (0.04) | 0.090 (0.09) | 0.090 (0.09) | 0.083 (0.08) | 0+0/2 | 0.094 (0.09) | 0.080 (0.08) | 0.064 (0.06) | 0.018 (0.02) |

(A) paper data, `a % N = 0`, threads=16: wall seconds (CPU seconds)

| N | builtin | node page | node query | node join† | skipped q+j/tasks† | flat query | flat join† | split query | split join† |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.136 (0.24) | 0.050 (0.53) | 0.057 (0.45) | 0.057 (0.45) | 0+0/16 | 0.056 (0.46) | 0.057 (0.54) | 0.047 (0.22) | 0.053 (0.24) |
| 10^1 | 0.082 (0.08) | 0.039 (0.41) | 0.040 (0.39) | 0.040 (0.38) | 0+0/24 | 0.041 (0.43) | 0.042 (0.47) | 0.029 (0.14) | 0.030 (0.14) |
| 10^2 | 0.056 (0.10) | 0.037 (0.42) | 0.036 (0.33) | 0.040 (0.36) | 0+0/24 | 0.036 (0.40) | 0.039 (0.33) | 0.025 (0.13) | 0.022 (0.12) |
| 10^3 | 0.074 (0.07) | 0.036 (0.37) | 0.037 (0.43) | 0.037 (0.42) | 0+0/24 | 0.038 (0.42) | 0.037 (0.42) | 0.026 (0.12) | 0.022 (0.10) |
| 10^4 | 0.064 (0.06) | 0.036 (0.27) | 0.036 (0.37) | 0.036 (0.43) | 0+0/24 | 0.040 (0.37) | 0.038 (0.42) | 0.024 (0.11) | 0.021 (0.10) |
| 10^5 | 0.062 (0.11) | 0.035 (0.36) | 0.036 (0.30) | 0.036 (0.36) | 0+6/24 | 0.037 (0.41) | 0.034 (0.24) | 0.028 (0.14) | 0.019 (0.08) |
| 10^6 | 0.047 (0.06) | 0.037 (0.40) | 0.037 (0.41) | 0.026 (0.12) | 0+15/24 | 0.036 (0.41) | 0.025 (0.19) | 0.026 (0.14) | 0.018 (0.03) |

(B) sorted `a`, `a < 10^6/N` — beyond the paper's scope, threads=1: wall seconds (CPU seconds)

| N | builtin | node page | node query | node join† | skipped q+j/tasks† | flat query | flat join† | split query | split join† |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.105 (0.11) | 0.147 (0.15) | 0.141 (0.14) | 0.159 (0.16) | 0+0/1 | 0.150 (0.15) | 0.188 (0.19) | 0.116 (0.12) | 0.132 (0.13) |
| 10^1 | 0.057 (0.06) | 0.115 (0.11) | 0.095 (0.09) | 0.087 (0.09) | 0+0/2 | 0.107 (0.11) | 0.086 (0.09) | 0.061 (0.06) | 0.032 (0.03) |
| 10^2 | 0.033 (0.03) | 0.088 (0.09) | 0.089 (0.09) | 0.081 (0.08) | 0+0/2 | 0.102 (0.10) | 0.082 (0.08) | 0.055 (0.05) | 0.021 (0.02) |
| 10^3 | 0.034 (0.03) | 0.087 (0.09) | 0.086 (0.09) | 0.078 (0.08) | 0+0/2 | 0.108 (0.11) | 0.079 (0.08) | 0.063 (0.06) | 0.025 (0.02) |
| 10^4 | 0.036 (0.04) | 0.088 (0.09) | 0.086 (0.09) | 0.080 (0.08) | 0+0/2 | 0.086 (0.09) | 0.080 (0.08) | 0.069 (0.07) | 0.021 (0.02) |
| 10^5 | 0.035 (0.04) | 0.086 (0.09) | 0.087 (0.09) | 0.081 (0.08) | 0+0/2 | 0.108 (0.11) | 0.080 (0.08) | 0.058 (0.06) | 0.021 (0.02) |
| 10^6 | 0.036 (0.04) | 0.085 (0.08) | 0.089 (0.09) | 0.100 (0.10) | 0+0/2 | 0.085 (0.09) | 0.082 (0.08) | 0.073 (0.07) | 0.021 (0.02) |

(B) sorted `a`, `a < 10^6/N` — beyond the paper's scope, threads=16: wall seconds (CPU seconds)

| N | builtin | node page | node query | node join† | skipped q+j/tasks† | flat query | flat join† | split query | split join† |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.127 (0.23) | 0.053 (0.51) | 0.052 (0.45) | 0.066 (0.58) | 0+0/16 | 0.070 (0.57) | 0.071 (0.60) | 0.049 (0.21) | 0.057 (0.24) |
| 10^1 | 0.056 (0.06) | 0.035 (0.40) | 0.037 (0.33) | 0.029 (0.19) | 0+14/24 | 0.037 (0.40) | 0.029 (0.12) | 0.030 (0.15) | 0.032 (0.05) |
| 10^2 | 0.039 (0.04) | 0.034 (0.42) | 0.035 (0.34) | 0.025 (0.18) | 0+15/24 | 0.038 (0.40) | 0.025 (0.22) | 0.025 (0.11) | 0.023 (0.04) |
| 10^3 | 0.019 (0.03) | 0.035 (0.27) | 0.036 (0.39) | 0.024 (0.12) | 0+15/24 | 0.035 (0.41) | 0.025 (0.15) | 0.029 (0.14) | 0.017 (0.03) |
| 10^4 | 0.036 (0.04) | 0.035 (0.29) | 0.035 (0.34) | 0.024 (0.17) | 0+15/24 | 0.035 (0.42) | 0.025 (0.22) | 0.030 (0.13) | 0.020 (0.04) |
| 10^5 | 0.037 (0.04) | 0.035 (0.28) | 0.035 (0.35) | 0.024 (0.17) | 0+15/24 | 0.043 (0.40) | 0.026 (0.12) | 0.030 (0.12) | 0.023 (0.03) |
| 10^6 | 0.035 (0.04) | 0.034 (0.35) | 0.036 (0.32) | 0.029 (0.13) | 0+15/24 | 0.034 (0.32) | 0.024 (0.18) | 0.031 (0.14) | 0.023 (0.04) |

**Interpretation**

- **`page` -> `query`: no difference - this reproduces the limitation the paper describes in Section 6.5: a condition
  on the parent cannot reduce the scan of the child.** In both experiments `node`/`flat` take the same time with and
  without filter pushdown (N >= 100: 1 thread 0.085-0.096s - `flat` in (B) up to 0.108s - and 16 threads
  0.034-0.043s, in both configurations). The predicate is on the
  parent (1M rows, cheap); the cost is the scan of the 10M child elements, which no condition on the parent can
  restrict without information from the join. `split` shows the same with stored keys: in `query` it stays at
  0.055-0.073s (1 thread) for N >= 100, as it also reads all 10M child rows.
- **`join` (beyond the paper's scope)**: the child scan skips tasks only when it has several of them - at 16 threads
  its row group is split into 16 parts; with 1 thread a node of a single row group is one task and nothing can be
  skipped (the 1-thread gains of up to ~10%, not at every N, come from evaluating the join filter on the child rows and decoding `b`
  only for the rows that pass). In (A) the selected keys are spread over the file: parts are skipped only from
  N = 10^5 (13 selected rows: 6 of 16 child parts) and at N = 10^6 (1 row: 15 of 16; wall 0.037s -> 0.026s, CPU
  0.41s -> 0.12s). In (B) 14-15 of the 16 child parts are skipped from N = 10 on: wall 0.035-0.037s -> 0.024-0.029s,
  CPU 0.32-0.39s -> 0.12-0.19s.
- **`join` slower than `split` - the fundamental cost of generating the keys on the fly: to skip, the levels must be
  counted first.** `split` in `join` reaches 0.017-0.032s at 16 threads and 0.018-0.032s even with 1 thread (N >= 10 in
  (B), N = 10^6 in (A)): its keys are stored, and the row group statistics of `_psk0` let it skip 9 of its 10 child row
  groups without reading them. The node scan has no stored keys: the keys at the start of every part are only known
  after the repetition levels of all pages of the child column have been counted, which decompresses the whole 80 MB
  column chunk before any part can be skipped (EXPLAIN ANALYZE of (B) N = 10^6: 173 MB read for an 84 MB file). The
  parts that remain are not the cost - this pre-pass is, and it is the same work whatever the selectivity.
- **This is a structural cost of the paper's approach, not of this implementation.** The paper says so itself: in
  Section 6.5, that the values of inner levels cannot be skipped, and in the explanation of Listing 3, that the
  repetition levels of the preceding pages are not known from the metadata and have to be scanned. `split` avoids the
  cost by storing the keys - in exchange for the paper's premise of reading the original nested file as it is
  (in situ): it needs a second, pre-split copy of the data, written in advance. Skipping without the pre-pass would
  need the key ranges of the pages without reading them - stored keys, or page-level skipping (phase 2) with page
  statistics (phase 3), which these parquet-cpp-arrow files do not have.
- **Page format of the paper's files**: all of them - nested and pre-split, parquet-mr (TPC-H SF10) and
  parquet-cpp-arrow (all others) - use data pages of version 1 (the type of the first data page of every column
  chunk, read from its page header), in which the levels are compressed together with the values.
  *Possible improvement*: with data pages v2 the repetition and definition levels are stored uncompressed, before and
  separate from the values, so the pre-pass could count the repetition levels without decompressing the values - this
  needs files written with v2 pages and a levels-only page read in the column reader (DuckDB's reader decompresses the
  values of a v2 page when it loads the page).
- `builtin` gets faster with selectivity at 1 thread (0.105-0.115s -> 0.033-0.043s): `read_parquet` evaluates the
  predicate on `a` first and decodes the list `b` only for the selected rows, within a single scan.

### Regression check on the paper's queries

The full query set, `page` vs `filter` (filter pushdown, default settings: `parquet_node_join_filter_pruning = false`,
join filter pushdown on), threads = 1 and 16, interleaved, 5 runs (`filter_<dataset>.csv`). Ratios filter / page of the
wall time (CPU time); `split` runs unchanged code and shows the noise of this machine: 0.83-1.17. All variants return
their expected results.

tpch_sf1: filter / page, wall (CPU)

| query | node t1 | node t16 | flat t1 | flat t16 | split t1 | split t16 |
|---|---|---|---|---|---|---|
| q01 | 0.89 (0.89) | 0.93 (0.91) | 0.99 (1.00) | 1.01 (1.00) | 1.11 (1.13) | 1.02 (1.02) |
| q03 | 0.98 (0.99) | 1.01 (0.97) | 1.01 (1.00) | 0.95 (0.90) | 0.88 (0.88) | 1.03 (1.01) |
| q04 | 1.12 (1.12) | 1.01 (0.95) | 0.99 (0.99) | 0.95 (0.94) | 1.03 (1.03) | 1.03 (1.01) |
| q06 | 1.08 (1.07) | 0.87 (0.87) | 1.10 (1.09) | 1.03 (0.99) | 1.05 (1.05) | 0.99 (0.98) |
| q10 | 1.13 (1.11) | 1.05 (1.04) | 1.04 (1.03) | 1.00 (0.83) | 0.92 (0.94) | 1.07 (1.08) |
| q12 | 1.04 (1.04) | 1.01 (0.99) | 0.99 (1.00) | 0.98 (1.01) | 0.83 (0.83) | 0.98 (0.96) |

tpch_sf10: filter / page, wall (CPU)

| query | node t1 | node t16 | flat t1 | flat t16 | split t1 | split t16 |
|---|---|---|---|---|---|---|
| q01 | 0.97 (0.97) | 0.73 (0.73) | 0.98 (0.98) | 0.99 (0.98) | 1.00 (1.00) | 0.99 (1.04) |
| q03 | 1.00 (1.00) | 1.12 (1.21) | 1.01 (1.01) | 1.04 (1.03) | 1.00 (0.98) | 0.94 (0.90) |
| q04 | 1.03 (1.02) | 1.20 (1.18) | 1.03 (1.03) | 1.05 (1.04) | 0.99 (0.98) | 1.05 (1.02) |
| q06 | 0.99 (1.00) | 1.00 (0.96) | 0.99 (0.98) | 1.03 (1.05) | 1.01 (0.99) | 0.93 (1.02) |
| q12 | 1.01 (1.01) | 0.83 (0.76) | 1.04 (1.04) | 1.00 (0.97) | 1.00 (1.00) | 0.98 (1.01) |

xmark: filter / page, wall (CPU)

| query | node t1 | node t16 | flat_umbra t1 | flat_umbra t16 | flat_minmax t1 | flat_minmax t16 | split t1 | split t16 |
|---|---|---|---|---|---|---|---|---|
| q02 | 0.97 (0.95) | 1.00 (0.98) | 1.02 (1.02) | 1.32 (1.10) | 1.02 (1.01) | 1.05 (1.11) | 0.96 (0.95) | 1.10 (1.06) |
| q03 | 1.03 (1.02) | 1.04 (1.06) | 0.95 (0.95) | 1.01 (0.91) | 1.03 (1.03) | 1.31 (1.27) | 0.97 (0.95) | 0.96 (1.17) |
| q04 | 1.03 (1.03) | 1.05 (1.04) | 1.39 (1.38) | 1.32 (0.90) | 1.03 (1.03) | 1.06 (1.04) | 1.00 (0.98) | 1.04 (0.87) |
| q04p | 1.00 (1.00) | 1.00 (1.04) | 1.05 (1.04) | 1.46 (1.00) | 0.98 (0.99) | 1.10 (1.11) | 0.96 (0.95) | 1.09 (1.13) |

dblp: filter / page, wall (CPU)

| query | node t1 | node t16 | flat t1 | flat t16 | split t1 | split t16 |
|---|---|---|---|---|---|---|
| q06 | 1.01 (1.01) | 1.07 (1.04) | 1.00 (1.00) | 0.98 (1.00) | 1.00 (1.01) | 1.05 (1.06) |
| q07 | 0.99 (1.00) | 0.95 (0.95) | 0.95 (0.95) | 1.16 (1.14) | 1.03 (1.03) | 1.17 (1.10) |
| q08 | 1.00 (1.00) | 1.03 (1.00) | 0.99 (0.99) | 0.96 (0.93) | 0.99 (0.98) | 1.01 (0.98) |
| q09 | 1.01 (1.01) | 1.20 (1.16) | 1.00 (1.00) | 0.98 (1.02) | 1.06 (1.07) | 1.06 (1.13) |

- TPC-H SF1/SF10 and DBLP: the node/flat ratios (0.73-1.20) lie in or just beside the noise range of `split`, in both
  directions, without a pattern.
  Their filters keep most rows of the large nodes, so there is little to gain. A filter in the scan replaces the
  FILTER above it at the same cost.
- XMark `flat_umbra` q04 (+15-20 ms at 1 and 16 threads, confirmed in a separate interleaved run with 10 runs) and
  q04p (+13 ms at 16 threads only): the join order flipped. Both queries are symmetric self-joins of the bidders of
  two persons, whose filtered scans now have equal estimates as table filters (default selectivity 0.2, the columns
  have no statistics). In q04, person51 has no bids in the matching auctions: the old plan built the hash table from that
  side (0 rows), so the probe-side scan stopped almost at once; the new plan builds from person20's side (3 rows) and
  the person51 scan reads the whole node (20 ms). In q04p both plans read both bidder scans completely and take the
  same time with 1 thread (0.066s vs 0.065s). The 16-thread difference comes from the flipped order, which changes
  what runs one after the other; not analysed further. The join filters are not the cause: disabling the join
  filter pushdown optimizer gives the same times.
- XMark `flat_umbra` q02 (1.32) and `flat_minmax` q03 (1.31) at 16 threads did not reproduce in a separate run with
  10 runs (q02 0.054s vs 0.051s; q03 0.049s vs 0.054s), in which all four `flat_minmax` queries were 1-5 ms slower.
- **`flat_minmax` profiled** (interleaved timings with 15 runs, and perf with `profile_breakdown.py`, 3 profiles per
  binary, 1 thread): the difference is **not** the evaluation of filters in the scan or the late decoding.
  - The plans of both binaries are identical, and no node scan of these queries gets a filter: the conditions on the
    persons (q02/q04/q04p) and on the increases (q03) stay in FILTER / join operators above the scans. The
    categories "scan filters / late decoding" (`FilterSelection`, filter executors, `ColumnReader::Select`) have no
    samples at all; decoding and key generation take the same time (q04: 14.0 vs 14.0 ms decoding, 3.0 vs 3.7 ms keys;
    q03: 9.7 vs 9.3 ms, 11.0 vs 9.0 ms).
  - The join filters, which the joins now build for the node scans (and the scans ignore with
    `parquet_node_join_filter_pruning = false`), take <= 0.7 ms, and disabling the join filter pushdown optimizer gives
    the same times as with it.
  - With 15 runs the difference is 0-2 ms (0-7%); an identical copy of the old binary differs from it by up to 2 ms in
    the same run (q03, 1 thread: 0.059s vs 0.061s, filter pushdown 0.064s). The rest of the profile difference lies in
    the aggregate and hash join (q03 +3.3 / +1.3 ms), which the change does not touch - within the noise of these
    40-65 ms queries; what remains (about 1 ms) could not be attributed at this resolution.

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
