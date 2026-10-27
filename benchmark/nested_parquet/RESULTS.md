# Nested Parquet benchmark: read_parquet_node / read_parquet_flat

Queries of the paper "Nested Parquet Is Flat, Why Not Use It?" (Rey et al., SIGMOD 2025), from
https://github.com/alicerey/nested-parquet, on the paper's datasets (Google Drive archive linked from that repository,
8,551,262,143 bytes; the Twitter dataset is not included).

This file holds the final results (2026-10-26). The earlier measurements and their analyses (laptop runs, the first
server runs, the split-rule and hardware experiments, the build comparison, the first three-binary run on the old
DuckDB, the selectivity and filter-pushdown experiments) were removed from the repository on 2026-10-26; they are in
commit `680aab9a8d` (`RESULTS.md` and the `server_2026*` folders and CSVs there).

## Differences from the paper (summary)

What this implementation and its measurements do differently from the paper.

**System and interface**
- The paper implements its approach in Umbra; here it is a DuckDB extension in the Parquet reader: the table functions
  `read_parquet_node(file, node := 'a.b')` (one node as a flat relation with `_sk`/`_ak*` key columns) and
  `read_parquet_flat(file)`, which an optimizer rule (`pre_optimize_function`) replaces by the scans of the nodes of
  the used columns and the joins on their keys. The existing `read_parquet` scan is not changed.
- Path syntax: Umbra's `Users.Posts.Comments`-style paths are written as quoted column names (`"Posts.Comments.Text"`) -
  no change to DuckDB's binder.
- Join semantics: a parent without children has no row in the result (INNER join semantics). Sibling nodes give
  every combination of their rows under their lowest common ancestor, which is the paper's "fully flattening"
  (Section 7). The extension with an outer join that the paper calls possible concerns "semi-flattening", where every
  tuple appears once; it is not implemented.
- Element order: Umbra's surrogate key per node is exposed as `"<path>._sk"`; a position within the list (`_pos`) is
  not implemented.
- Keys follow the paper (dense, placeholders of empty/NULL lists counted, row-group offsets from the metadata).
- **Empty lists (our choice, differs from the paper's Fig. 5)**: Fig. 5 shows the placeholders of empty lists as rows
  of the node relations (Likes `sk` 0 and 1, Comments `sk` 1, Reactions `sk` 0); with them, a parent without children
  joins its placeholder and appears once with NULL children. The paper does not say how queries treat these rows.
  Here the placeholders are not returned by default (`include_empty := true` returns them as NULL rows), so a parent
  without children has no row in a join - the semantics of DuckDB's `UNNEST`, which drops empty lists, so that the
  flat queries return the results of the builtin queries. Only XMark Q2 differed: the authors' builtin query indexes
  the list, so `bidder[1]` gives a NULL row for each of the 11,586 auctions without bidders (NULL lists in
  `sf10.parquet`), which every other form joins away. The builtin query now keeps only the auctions with bidders
  (`where len(a.bidder) > 0`), so all forms are compared with it directly.

**Parallel scan (paper: Listing 3)**
- A row group is split only when there are fewer row groups than threads - and, when the keys need a count of its
  levels, fewer than physical cores that run the threads (decided on the 2-socket server: beyond the cores, threads are
  hyper-threads, which gain less than the count costs). With 1 thread, or row groups that are not split, the scan is
  the unchanged single scan.
- The parts start at the page boundaries of the largest column that is read (the paper's per-page jumps) - or at
  offsets within its pages when it has fewer pages than threads (Listing 3's offset). The keys at the start of a part
  come from a pre-pass that counts the repetition levels per page (reading neither the dictionary nor the values), in
  parallel, once per query, shared by the parts and by all scans of the same column chunk. Minimum part size: 122,880
  slots (`parquet_node_task_slots`).
- Limitation: columns with few pages (XMark bidders: 1-8 pages) are split within pages, which every part then
  decompresses.
- Limitation: short queries over a single row group (XMark, 60-120 ms with 1 thread) are slower with 10-40 threads than
  with 1 thread on the 2-socket server (see "Final results").

**Filters (phase 1 only)**
- Filters are evaluated in the scan after key generation, the other columns are decoded only for the rows that pass,
  and whole tasks (row groups / parts) are skipped by key ranges and column chunk statistics. Page-level skipping and
  page statistics (phases 2 and 3) are not implemented.
- Skipping with the filters that joins create while the query runs (sideways information passing, which the paper only
  names as future work in Section 6.5) is an addition beyond the paper's scope, off by default
  (`parquet_node_join_filter_pruning`).
- In the selectivity experiment the flat queries also run with DuckDB's `join_filter_pushdown` optimizer disabled, to
  leave out sideways information passing beyond the paper's scope. The other datasets run with DuckDB's default
  optimizers.
- As in the paper (Section 6.5, Listing 3), skipping parts of a child requires counting the repetition levels of its
  pages first: a structural cost of reading the nested file in situ that stored keys (`split`) avoid.

**Benchmark setup**
- Hardware and software: a lab server (Xeon Gold 5215, 2 sockets x 10 cores, 40 hardware threads) instead of the
  paper's server; DuckDB v2.1.0-dev release builds. Binaries of different commits can differ by up to 10% at 1 thread
  on this server from code layout alone (same instructions, fewer per cycle), so small differences between binaries
  are not meaningful.
- Compared systems: the paper compares Umbra with other systems; here everything runs in DuckDB - `builtin` (DuckDB's
  nested types with UNNEST) on the original DuckDB and on prenest-3way-base, and `flat` (this implementation).
- Baseline: `base` is a809d3cd51, the commit of DuckDB main that main_rey branches from (the merge base of main_rey and
  DuckDB main, and the parent of main_rey's first commit 87b27256b9; no merges since). prenest-3way-base is on the
  same commit, so all three binaries share the same DuckDB underneath.
- Datasets: the paper's archive without the Twitter dataset. All files use data pages v1; only the parquet-mr files
  (TPC-H SF10) have a page index.
- Queries: the authors' repository, with these changes - XMark Q2's builtin query restricted to the auctions with
  bidders (see "Empty lists"), XMark Q4 compared with oracles where the semantics differ (every pair of bids), q04p
  added (Q4 returns no rows), arrow lambdas rewritten (`lambda x: ...`), XMark element order through `"<path>._sk"`
  in two forms (Umbra's correlated subqueries, and a min/max join).
- Selectivity experiment (Fig. 15): every variant computes `avg(greatest(a, b))` (the paper's builtin query computes
  `avg(b)`); experiment (B) with sorted data and a range predicate is an addition beyond the paper's scope. With 1
  thread, builtin is faster than flat for every N >= 10, unlike the paper's Fig. 15 (see "Final results").

Variants per query (`queries/<dataset>/<query>.<variant>.sql`):
- `builtin`: the repository's DuckDB query over the nested file (UNNEST of nested types)
- `node`: `read_parquet_node` on the nested file with the joins on `_sk`/`_ak*` written by hand
- `flat`: the builtin query over `read_parquet_flat`, every path aliased to its short name in one subquery (this also
  exercises the analysis of the used columns)
- `flat_umbra` / `flat_minmax` (XMark): the element order through the `"<path>._sk"` columns of `read_parquet_flat` -
  Umbra's queries translated as they are (correlated subqueries with min/max of the key per auction `_id`), and a join
  with the min/max key per parent (`GROUP BY "open_auctions.open_auction._sk"`)
- `split`: the repository's normalized query over the paper's pre-split files with stored keys

The final run measures `builtin` and `flat` (XMark: `flat_minmax`, the faster of the two element-order forms).

A variant's result is compared with the builtin one by an order-insensitive hash (numbers rounded to 2 decimals and then
to 12 significant digits), or with `<query>.<variant>.oracle` where the variant has a different result by definition
(XMark Q4, see below). The 12 digits absorb a last-bit difference between DuckDB versions: since commit 363a7253e8
(2026-03-02), DuckDB's `aggregate_function_rewriter` turns an ungrouped `avg(x)` into `sum(x) / count(x)` in DOUBLE,
which rounds twice and can be 1 ULP off the exact mean, whereas older DuckDB versions divide in long double
(selectivity `avg(greatest(a, b))` over values near 2^63).

## Running

On the server, with the kit of `SERVER.md` (step 12):

```
./run_all.sh --base <original duckdb> --final <main_rey duckdb> --prenest <prenest-3way-base duckdb> \
             --data <datasets dir> --threads "1 10 20 40"
```

`run_all.sh` checks the data files, runs `run_bench.py` per dataset, compares the results (`result_check.txt`) and
writes `summary.md`. The queries come from `make_queries.py` (builtin, node, split), `make_flat_queries.py` (flat)
and `make_selectivity_queries.py`.

## Method

- All configurations are compared **interleaved**: for every query, every binary and thread count runs one after the
  other, and the fastest of 10 runs is taken. Differences between separate runs are not meaningful.
- `run_bench.py` samples the CPU use of other processes before every query (column `busy_cpu`) and does not start when
  other processes keep more than half a core busy; it kills the process group of a query on a timeout or when it is
  interrupted.
- Geometric means are over the queries of a dataset; queries with a failed or oracle-only comparison would be left
  out (none in the final run).

## Final results: original DuckDB, prenest-3way-base, main_rey (2026-10-26)

`run_all.sh --prenest ...` (`SERVER.md`, step 12) on the lab server (Intel Xeon Gold 5215, 2 sockets x 10 cores, 40
hardware threads, 125 GiB), threads = 1/10/20/40, fastest of 10 runs, `busy_cpu` = 0, one run for all datasets.
**All 66 results (flat and prenest for each of the 33 queries) equal the builtin results of `base`, without
oracles.** Files: `server_20261026_3way_base/` (CSVs, `summary.md`, `result_check.txt`, `run_info.txt`, logs, and
`three_binaries.xlsx` with all numbers and charts).

| configuration | binary | query |
|---|---|---|
| `base` | original DuckDB a809d3cd51 | builtin |
| `prenest` | prenest-3way-base fabde05fe6, `parquet_prenest_auto = true` | builtin |
| `final` | main_rey 2d6066fd4d | flat (XMark: flat_minmax) |

**prenest-3way-base** is DataFusion's pre-nest filter pushdown ported into DuckDB's existing UNNEST path, on the same
DuckDB commit as `base`: 548a58078e prunes unused LIST<STRUCT> fields (projection pushdown), fabde05fe6 pushes
predicates on list elements into the list assembly of the Parquet reader (`parquet_prenest_auto`). It is the branch
prenest-3way (e2e140aa2d, on the older DuckDB 83ae79e5b7) moved onto a809d3cd51. The port only adapts the code to the
newer DuckDB APIs and passes the filter through the multi-file wrapper of the newer `read_parquet`; it adds nothing
else. Before the run, all prenest tests and DuckDB's copy/optimizer/nested/list/pragma/table_function/explain suites
passed, and the pre-nest counters (`elements_decoded`, `elements_appended`) of the old and the new branch were equal
on TPC-H SF1, XMark, DBLP (server) and the selectivity files (laptop). An earlier run with the old branch mixed in
differences of the older DuckDB: it was 1.5-5.4x faster than base on the selectivity data, where neither change
applies. That is why the branch was moved.

base seconds / seconds of the configuration, geometric mean over the queries, threads = 1 / 10 / 20 / 40 (> 1: faster
than the original DuckDB):

| dataset | prenest | flat (main_rey) |
|---|---|---|
| TPC-H SF1 | 5.49 / 5.50 / 5.47 / 5.44 | 15.34 / 52.09 / 49.00 / 46.62 |
| TPC-H SF10 | 5.27 / 5.04 / 5.06 / 4.85 | 8.92 / 8.52 / 8.50 / 8.17 |
| XMark | 3.82 / 3.79 / 3.78 / 3.84 | 6.99 / 6.16 / 5.96 / 5.66 |
| DBLP | 0.99 / 0.98 / 1.01 / 0.99 | 0.82 / 1.35 / 2.11 / 2.47 |
| Selectivity (A), a % N = 0 | 0.99 / 1.07 / 1.01 / 0.82 | 0.73 / 2.89 / 2.93 / 2.93 |
| Selectivity (B), a < 10^6 / N | 0.98 / 0.94 / 1.04 / 0.99 | 0.41 / 1.22 / 1.48 / 1.55 |

TPC-H, seconds base / prenest / flat:

| query | SF1, 1 thread | SF1, 40 threads | SF10, 1 thread | SF10, 40 threads |
|---|---|---|---|---|
| q01 | 6.49 / 3.75 / 0.63 | 6.49 / 3.77 / 0.12 | 34.9 / 17.1 / 6.26 | 2.79 / 1.45 / 0.42 |
| q03 | 5.94 / 1.89 / 0.41 | 5.94 / 1.88 / 0.17 | 29.8 / 5.74 / 3.52 | 2.46 / 0.52 / 0.38 |
| q04 | 5.96 / 0.73 / 0.33 | 5.92 / 0.74 / 0.13 | 30.2 / 5.17 / 3.08 | 2.46 / 0.47 / 0.36 |
| q06 | 6.09 / 0.66 / 0.33 | 6.01 / 0.65 / 0.06 | 31.1 / 3.92 / 2.68 | 2.54 / 0.36 / 0.19 |
| q10 | 5.97 / 0.89 / 0.43 | 5.93 / 0.88 / 0.25 | - | - |
| q12 | 6.29 / 0.63 / 0.34 | 6.33 / 0.66 / 0.11 | 32.5 / 3.89 / 3.08 | 2.68 / 0.34 / 0.29 |

XMark and DBLP, seconds base / prenest / flat:

| query | 1 thread | 40 threads |
|---|---|---|
| XMark q02 | 0.561 / 0.133 / 0.061 | 0.550 / 0.134 / 0.079 |
| XMark q03 | 0.562 / 0.151 / 0.116 | 0.583 / 0.152 / 0.142 |
| XMark q04 | 0.570 / 0.152 / 0.075 | 0.582 / 0.151 / 0.092 |
| XMark q04p | 0.572 / 0.158 / 0.081 | 0.567 / 0.159 / 0.100 |
| DBLP q06 | 3.371 / 3.457 / 4.065 | 1.035 / 1.095 / 0.409 |
| DBLP q07 | 4.557 / 4.500 / 5.399 | 1.222 / 1.217 / 0.580 |
| DBLP q08 | 1.333 / 1.375 / 1.934 | 0.460 / 0.460 / 0.196 |
| DBLP q09 | 2.420 / 2.458 / 2.573 | 0.766 / 0.769 / 0.256 |

All queries and thread counts: `server_20261026_3way_base/summary.md` and `three_binaries.xlsx`.

- **flat (main_rey) is the fastest on every TPC-H and XMark query at every thread count.** Compared with prenest, it
  is 1.3-6.0x faster with 1 thread and 1.2-30x with 40 threads on TPC-H, and 1.3-2.2x and 1.1-1.7x on XMark.
- **TPC-H SF1 has a single row group.** The builtin queries of base and prenest therefore take the same time with 1
  and 40 threads. flat splits the row group and is 23-104x faster than base with 10-40 threads.
- **prenest helps TPC-H (4.9-5.5x) and XMark (3.8x).**
  - On TPC-H, q03/q04/q06/q10/q12 have predicates on list elements that keep 0.5-20% of the elements read (SF1
    counters). q01's predicate keeps 98%.
  - XMark's predicates are not on list elements, so its gain is the field pruning of the wide auction structs
    (measured in the follow-up below: `prenestoff` = `prenest` on XMark).
- **On DBLP and the selectivity data, prenest equals base** (geometric means 0.82-1.07). Single queries of 0.05-0.3 s
  vary by up to +-40% at 20-40 threads, in both directions. Their predicates are on the parent `a`, not on list
  elements, and selectivity's `b` is a `LIST<BIGINT>` with no fields to prune, so neither change applies.
- **TPC-H SF10 dates are pushed down.** The SF10 queries compute dates as `date '...' +- interval`. a809d3cd51 binds
  this as a DATE comparison without a cast on the column (`l_shipdate <= '1998-09-02'::DATE`; q06:
  `l_shipdate BETWEEN ...`), so prenest pushes it into the scan. The older DuckDB under the original prenest-3way bound
  it as `CAST(l_shipdate AS TIMESTAMP) <= ...`, which the pre-nest rules refuse.
- **On DBLP and the selectivity data with 1 thread, flat is slower than base.**
  - DBLP is at 0.82x. For N >= 10, selectivity (A) is at 0.39-0.91x and (B) at 0.28-0.43x. Only the unfiltered N = 1
    is about equal or faster.
  - **This differs from the paper's Fig. 15.** A likely reason is that DuckDB's own Parquet scan has improved since
    the version the paper measured. `read_parquet` evaluates the predicate on `a` during the scan and decodes the list
    `b` only for the rows that qualify. The flat plan reads all of the child node and joins it with the parent; the
    condition on the parent does not reduce the child scan (Section 6.5).
  - With 10-40 threads, flat is faster again: DBLP 1.35-2.47x, selectivity (A) 2.9x, (B) 1.2-1.6x. The joins of the
    flat plan parallelize, while the builtin scans do not go beyond their row groups (DBLP 6, selectivity 1).
- **XMark flat is slower with 10-40 threads than with 1 thread** (q02 0.061 s -> 0.077-0.080 s). The file has a single
  row group, which is split, and its bidders column has few pages (limitation above).
- **Scaling above 10 threads is not linear.** Up to 10 threads run on one socket; beyond that the threads span both
  sockets (NUMA), and beyond 20 they share cores (hyper-threading).

## Follow-up checks (2026-10-27)

Four questions left by the 2026-10-26 run, and one that the answers raised (why flat is slower with 5 row groups),
measured with the same three binaries on the same server, threads = 1/20 (20 = the physical cores), fastest of 10
runs, `busy_cpu` = 0; then everything again with a cold page cache (last subsection: median of 5 runs). `followup_checks.sh` runs every step; files: `followup_20261027_0127/` (`meta.tsv`,
`rewrite.txt`, `off/`, `rg1/`, `rg20/`, `split/`, `cold/`, `q01_counters.txt`, `explain_selectivity_sorted/`). **All 303
results equal the builtin results of `base`** (off 99, rg1 72, rg20 60, split 72).

### How much of flat's multi-thread lead is parallelism?

`parquet_metadata()` of the paper's files:

| file | row groups | top-level rows | can be split |
|---|---|---|---|
| TPC-H SF1 `nestedregion.parquet` | 1 | 5 (regions) | into at most 5 |
| XMark `sf10.parquet` | 1 | 1 | no |
| selectivity (A), (B) `l1.parquet` | 1 | 1,000,000 | yes |
| TPC-H SF10 / DBLP | 22 / 6 | | (already several) |

A row group holds whole top-level rows, so SF1 can have 5 row groups at most and XMark only one. SF1 and the
selectivity files were rewritten with pyarrow 26.0.0 (snappy, like the originals) twice: one row group (`rg1`, the
control) and `ceil(rows / 20)` rows per row group (`rg20`: 5 row groups for SF1, 20 for the selectivity files).
Compare `rg1` with `rg20`, not with the original files: the rewrite alone changed flat's 20-thread times (SF1 q03
0.164 s -> 0.255 s, q10 0.264 s -> 0.391 s), because pyarrow 26 writes far fewer pages (next section).

base / flat, geometric mean:

| dataset | 1 thread rg1 | 1 thread rg20 | 20 threads rg1 | 20 threads rg20 |
|---|---|---|---|---|
| TPC-H SF1 | 15.20x | 12.40x | 34.08x | **6.47x** |
| selectivity (A) | 0.74x | 0.61x | 3.23x | **0.69x** |
| selectivity (B) | 0.41x | 0.12x | 1.28x | **0.36x** |

- **Most of flat's multi-thread lead on single-row-group files is base not parallelizing.** With 5 row groups, base
  runs SF1 at 20 threads in 1.47-1.66 s instead of 5.87-6.45 s (it can use 5 threads), flat stays at 0.10-0.39 s, and the
  lead drops from 34x to 6.5x. The 1-thread ratio (15.3x on the original file, 12.4x on rg20) is the number without
  parallelism. With 20 row groups, base beats flat on the selectivity data at 20 threads.
- **On selectivity (B), base also skips row groups.** `a` is sorted, so `a < 10^6 / N` excludes 19 of the 20 row
  groups by their min/max statistics: base with 1 thread goes from 0.058-0.073 s to 0.010-0.043 s for N >= 10. flat
  does not get this (0.170-0.183 s -> 0.161-0.177 s), so (B) at rg20 is row group skipping as well as parallelism.
- **flat is slower on some SF1 queries with 5 row groups at 20 threads**: q03 0.255 -> 0.370 s, q04 0.160 -> 0.308 s,
  q12 0.138 -> 0.269 s. The cause is splitting row groups within their only page (next section).
- base with 1 thread is 15-20% faster on rg20 than on rg1 for SF1 (5.9-6.5 s -> 4.9-5.3 s): smaller row groups, not
  parallelism.
- XMark cannot be split; its 1-thread ratio (6.9x) is the one to use.

### Why flat is slower with 5 row groups: parts that start within a single page

`followup_checks.sh --steps split` (`followup_20261027_0127/split/`): the `read_parquet_node` debug log of every SF1
flat query at 20 threads, and the flat queries at 20 threads, fastest of 10 runs, with the default
`parquet_node_task_slots` (122,880), x2, x4, and with `parquet_node_physical_cores = 1`, which leaves the scans that
count levels unsplit. All 72 results equal the builtin results of `base`; `busy_cpu` = 0. Times in this run differ
from the `rg` step by up to 25% (rg1 q01 0.185 s here, 0.147 s there), so compare within the run.

Pages of the lineitem columns in the row group(s), from the log:

| file | writer | l_shipdate | l_extendedprice | l_orderkey | lineitem scan |
|---|---|---|---|---|---|
| original | parquet-cpp-arrow 13.0.0 | 10 | 46 | 44 | q01/q03: 16 parts, at the pages of `l_extendedprice` |
| rg1 | pyarrow 26.0.0 | 5 | 5 | 5 | 20 parts, within the pages |
| rg20 | pyarrow 26.0.0 | 1 per row group | 1 | 1 | 5 x 9 parts, within the one page |

flat at 20 threads, seconds (CPU seconds):

| file | query | default | task slots x4 | no split when counting |
|---|---|---|---|---|
| rg20 | q03 | 0.361 (3.31) | 0.219 (1.22) | **0.180** (0.74) |
| rg20 | q04 | 0.303 (2.31) | 0.197 (1.01) | **0.162** (0.82) |
| rg20 | q10 | 0.386 (3.08) | 0.245 (1.37) | **0.217** (0.91) |
| rg20 | q12 | 0.257 (2.19) | 0.202 (1.10) | **0.126** (0.61) |
| rg20 | q01 | 0.158 (2.53) | 0.135 (1.09) | 0.147 (2.27) |
| original | q03 | **0.160** (1.67) | 0.176 (1.36) | 0.413 (0.42) |
| original | q12 | **0.102** (1.36) | 0.170 (1.28) | 0.341 (0.65) |

- **When a row group has fewer pages than parts, every part starts within a page, and that page is decompressed by
  every part that starts in it.** On rg20 the 9 parts of a row group all start in the single page of each column. The
  scans of q03/q04/q10/q12 also need ancestor keys, so the rows before every part are counted in that page as well.
  The CPU time at 20 threads is 2.2-3.3 s against 0.34-0.43 s with 1 thread.
- **Not splitting is faster there.** With one task per row group (5 tasks, no counting), q03/q04/q10/q12 take 0.13-0.22 s
  instead of 0.26-0.39 s. The split rule only compares the number of row groups with the threads and cores
  (5 < min(20, 20)); it does not look at the pages.
- On the single-row-group files, splitting is still right: unsplit, the one task takes 0.30-0.44 s.
- q10 is affected as well. It did not look slower on rg20 in the `rg` step because it was already slow on rg1 (0.39-0.44
  s), where its lineitems are also split within pages.
- q01/q06 count no levels, so `no split when counting` does not change them; fewer parts (x2, x4) still help them
  somewhat (q01 0.158 -> 0.114-0.135 s).
- On the original file, the lineitem scans that read a column with many pages are split at page boundaries (q01/q03
  at the 46 pages of `l_extendedprice`); q04 reads only `l_commitdate`/`l_receiptdate` (10 pages) and is split within
  them. On the original file none of the tested settings is more than 7% faster than the default (q10 0.260 ->
  0.243 s with x2), so the main table above stands.

### Is prenest with `parquet_prenest_auto = false` equal to base?

No, and it should not be: prenest-3way-base is base plus exactly two commits, 548a58078e (LIST<STRUCT> field pruning)
and fabde05fe6 (pre-nest filter pushdown), and `auto = false` turns off only the second. So base / prenestoff is the
pruning and prenestoff / prenest is the filter pushdown (strictly, prenestoff still carries the inactive filter code,
whose cost was not measured separately). 1 thread, geometric mean (with 20 threads within 6% on TPC-H and XMark):

| dataset | base / prenest | pruning: base / prenestoff | filter: prenestoff / prenest |
|---|---|---|---|
| TPC-H SF1 | 5.50x | 1.73x | 3.19x |
| TPC-H SF10 | 5.25x | 2.14x | 2.45x |
| XMark | 3.75x | 3.77x | 1.00x |
| DBLP | 0.98x | 0.99x | 0.99x |
| selectivity (A) / (B) | 0.98x / 1.00x | 0.97x / 1.06x | 1.01x / 0.95x |

XMark's gain is all pruning. On TPC-H the filter's share depends on the query: SF1 q06 3.482 s -> 0.637 s (5.5x),
q01 3.879 s -> 3.820 s (1.02x).

### q01: pruning or filtering?

q01's 1.69x with 1 thread (6.472 s -> 3.820 s) is 1.67x pruning (-> 3.879 s) and 1.02x filtering. Its predicate
`l_shipdate <= date '1998-12-01' - interval '90' day` keeps 5,916,591 of the 6,001,215 lineitems (98.59%), so the
filter has almost nothing to drop. In the plan with `auto = true`, the scan shows the pushed predicate (`Pre-nest
Filters`) and the UNNEST already emits 5,916,591 rows. The pruning shows as data read: 104.8 MB (the seven lineitem
columns) instead of 304.3 MB (all of `r_nations`).

What the counters count (prenest-3way-base, fabde05fe6):

- `elements_appended` (5,916,591): elements that passed and were appended to their list - equal to the count of
  passing lineitems.
- `elements_decoded` (6,051,219): values the list reader pulled from its child reader, i.e. the rep/def slots of the
  leaf, which include one placeholder per empty or NULL list further up. 6,051,219 = 6,001,215 lineitems + 50,004
  customers without orders (0 regions without nations, 0 nations without customers, 0 orders without lineitems). The
  pass rate is therefore appended / lineitems, not appended / decoded.
- `predicate_elements` (6,849,935): elements given to the predicate. When the output vector is full, the rest of the
  child vector is carried into the next read and evaluated again, so carried values count twice: 6,849,935 - 6,051,219
  = 798,716 values over 756 carry-overs (1,056 on average, about half a vector). The results are unaffected; it is 13%
  more predicate evaluations than needed.

### Selectivity (B): where flat's 0.17 s with 1 thread comes from

EXPLAIN ANALYZE of the flat queries (main_rey, query settings) with 1 thread: the predicate `a < 10^6 / N` reaches the
scan of the top-level node (`Filters: a < 1000`, 1,000 rows, 20 ms), but not the scan of the child node `b`, which
reads all 10,000,000 elements for every N (130-190 ms of 0.20-0.29 s query time); the hash join then drops all but the matching
ones. The query settings turn off join filter pushdown, the only way the parent's condition could reach the child
scan. The builtin n3 is a single scan that returns 1,000 rows in 20 ms (0.098 s in total). CLI startup (0.06-0.07 s
for `SELECT 1`) is in the wall-clock times of both and is not the floor.

### Cold page cache

All numbers above are warm: the fastest of 10 runs in one process, with the files in the OS page cache.
`followup_checks.sh --steps cold` (`run_cold.py`, `followup_20261027_0127/cold/`) measures the same four configurations
on the original files with a cold cache: before every run the query's Parquet files are evicted with
`posix_fadvise(POSIX_FADV_DONTNEED)` (no root; other users' cache untouched) and every run is a new CLI process. The
time is the CLI's own query time (no process startup); MB is what the process read from disk (`/usr/bin/time %I`). 5
runs per configuration, interleaved, median. 1,320 runs, none failed, and `mincore` found 0.0% of any file still
cached before any run. The files are on a SATA SSD (Samsung 860, ext4; a cold `cat` of SF1 reads 304 MB in 0.56 s,
about 545 MB/s). The cold runs are steadier than the warm ones: the interquartile range is a median 1-7% of the
median per dataset (at most 20%, selectivity). Results were not compared in this step (`run_bench.py` did that above).

base / configuration, geometric mean, warm -> cold:

| dataset | threads | prenestoff (pruning) | prenest | flat |
|---|---|---|---|---|
| TPC-H SF1 | 1 | 1.73x -> 1.73x | 5.50x -> 4.99x | 15.26x -> 13.51x |
| TPC-H SF1 | 20 | 1.72x -> 1.73x | 5.43x -> 5.04x | 47.81x -> 26.76x |
| TPC-H SF10 | 1 | 2.14x -> 2.23x | 5.25x -> 5.01x | 8.89x -> 7.99x |
| TPC-H SF10 | 20 | 2.03x -> **3.68x** | 5.08x -> 5.67x | 8.50x -> 6.79x |
| XMark | 1 | 3.77x -> 4.14x | 3.75x -> 4.15x | 6.90x -> 8.58x |
| XMark | 20 | 3.79x -> 4.12x | 3.78x -> 4.10x | 6.08x -> 8.31x |
| DBLP | 1 | 0.99x -> 0.99x | 0.98x -> 1.00x | 0.81x -> 0.90x |
| DBLP | 20 | 1.01x -> 1.00x | 1.01x -> 1.00x | 2.03x -> 1.28x |
| selectivity (A) | 1 | 0.97x -> 1.00x | 0.98x -> 1.01x | 0.71x -> 1.25x |
| selectivity (A) | 20 | 1.05x -> 1.01x | 0.99x -> 1.02x | 3.03x -> 1.25x |
| selectivity (B) | 1 | 1.06x -> 0.99x | 1.00x -> 0.99x | 0.44x -> 0.87x |
| selectivity (B) | 20 | 0.99x -> 1.02x | 0.99x -> 1.01x | 1.30x -> 0.87x |

- **The field pruning reads 4-14x less from disk.** base reads the whole file for every query (SF1 290 MB, SF10
  2.5-2.6 GB, XMark 122 MB); prenestoff and prenest read only the projected columns (SF1 34-75 MB, SF10 318-599 MB,
  XMark 9-11 MB), and flat about as much (SF1 35-81 MB, SF10 303-600 MB, XMark 4-7 MB). prenest reads exactly what
  prenestoff reads: the pre-nest filter drops elements after they are decoded, so it saves CPU, not I/O.
- **Where base is bound by the disk, the pruning gains.** SF10 at 20 threads: base takes 4.8 s longer cold (2.6 GB at
  the SSD's speed), prenestoff 0.5 s, and the pruning's share grows from 2.0x to 3.7x. On XMark (122 MB vs 9-11 MB)
  prenest gains from 3.8x to 4.1x and flat from 6.1-6.9x to 8.3-8.6x.
- **flat's multi-thread lead shrinks where its warm time was close to the read time.** SF1 at 20 threads: flat reads
  47-81 MB, 0.13 s more than warm, and the 48x becomes 27x. DBLP at 20 threads: 2.0x -> 1.3x.
- **On the short queries all configurations add about the same read time**, so the ratios move towards 1: DBLP and
  the selectivity data read the same 81-354 MB in every configuration (`LIST<BIGINT>` / predicates on the parent: no
  pruning). prenest stays equal to base.
- **With 1 thread, flat's time grows less than base's for the same bytes**: on the selectivity files +0.07-0.08 s
  against +0.14-0.19 s for 81-85 MB, on DBLP +0.31 s against +0.52 s. So flat goes from 0.44-0.71x to 0.87-1.25x on
  the selectivity data. Why (overlap of reads and decoding, prefetching) was not measured.
- flat reads more with 20 threads than with 1 on some SF1 queries (q04 35 -> 47 MB, q10 62 -> 81 MB, q12 38 -> 52 MB);
  the cause was not measured.

## XMark: element order

The XMark queries need the order of the bidders of an auction. Umbra exposes a surrogate key per node (`"...bidder.sk"`);
`read_parquet_flat` exposes the same as `"<path>._sk"` (the row number of the node in the file, in element order).

- **Q2**: the authors' builtin query returns a row for every auction (120,000), with NULL for the 11,586 auctions
  without bidders (`bidder[1]` of an empty list), which the joins of every other form drop. The builtin query keeps
  only the auctions with bidders (108,414 rows), and all variants are compared with it.
- **Q3**: auctions without bidders have no first/last increase in any variant - all compare with the builtin query.
- **Q4**: the builtin query returns an auction once when the first bid of person20 is before the first bid of
  person51; Umbra's (and the split) query returns every pair of such bids. `flat_minmax` and `node` have the builtin
  semantics; `flat_umbra` and `split` are compared with `q04.flat_umbra.oracle` / `q04.split.oracle` (every pair of
  positions, from the nested lists).
- **q04p**: person20 and person51 never bid in the same auction, so Q4 returns no rows and checks nothing. q04p is Q4
  with person148112 and person189013, who bid in 41 common auctions.
- Correlated subqueries (`flat_umbra`) vs a join with the min/max key per parent (`flat_minmax`): the join is faster
  for all queries (laptop, 16 threads: Q2 0.024s vs 0.041s, Q3 0.046s vs 0.125s, Q4 0.025s vs 0.036s, Q4p 0.028s vs
  0.039s), so the final run uses `flat_minmax`.

## Filter pushdown into read_parquet_node (phase 1)

`read_parquet_node` accepts filters (`filter_pushdown`, generic expressions via `pushdown_expression`), which
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
  passing, which the paper only names as future work (Section 6.5) - **this setting is an addition beyond the paper's
  scope** and is off in the final run. With the setting off, these filters are ignored (the joins apply them anyway,
  so results are the same).
- Scope: phase 1 only. Skipping at page granularity (phase 2) and with page statistics (phase 3) are not implemented.

**Page index in the paper's datasets** (checked in the footers with pyarrow): ColumnIndex/OffsetIndex (page statistics)
are present in every column chunk only in the parquet-mr files - TPC-H SF10, nested and normalized. The
parquet-cpp-arrow files (TPC-H SF1, XMark, DBLP, synthetic) have none. All files have column chunk statistics.

## Notes

- XMark Q4 builtin: the repository's `x -> ...` lambdas were rewritten to `lambda x: ...` (arrow lambdas are disabled
  in this build); semantics unchanged.
- A bug found by these runs and fixed: a top-level column chunk with only NULL values (DBLP `year`, row group 4) is
  skipped by the column reader without advancing its count of remaining values -> hang / TProtocolException.
