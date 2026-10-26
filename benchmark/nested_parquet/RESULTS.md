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
  - XMark's predicates are not on list elements, so its gain is likely the field pruning of the wide auction structs.
    This was not measured separately.
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
