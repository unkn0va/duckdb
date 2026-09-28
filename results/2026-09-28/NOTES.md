# Measurement notes — 2026-09-28, local WSL2

Machine: local WSL2 (not apache2/apache10). Data: `~/tpch-nested/1/` (TPC-H SF1,
`tpch-nested` variant) and the synthetic fixture in the test file.
Build: `GEN=ninja make release`. Base before the fix: `c1317d78f8`.
Commits: **`753246123e`** (fix), **`8b6ff90656`** (regression test).
All measurements under `PRAGMA disable_verification`.

## The bug

`SafeToTruncate` allowed the truncation when the query read the target list — or a
value containing it — through an operator the path walk cannot cross. The reader
then dropped elements and whatever read the list above saw the truncation, so the
answer was wrong.

## Cause

`ResolveBindingPath` (`prenest_filter_pushdown.cpp:556`) walks a binding down to a
scan column through `LOGICAL_GET`, `LOGICAL_PROJECTION` and `LOGICAL_UNNEST`, and
returns false at anything else (598). An operator that re-binds a value under its
own table index — `LOGICAL_SET_OPERATION`, `LOGICAL_CTE_REF`, recursive CTE — ends
the walk. Every check that depends on it then goes quiet at once:

- `ContainerReadScanner::Scan` 974 is false, so 977–978 never raise `illegal`;
  982 descends into the pieces, each of which resolves to nothing.
- the result-binding loop's `&&` short-circuits on the left, which is *not* a
  refusal, so the output check passes.
- nothing lands in `iterated`, but the predicate branch's own UNNESTs do, so the
  exactly-once check and the "is it iterated at all" check both pass.

The forwarding skip (939, 949–950) sets this up: a Projection that merely
re-exports the value is skipped on the premise that whoever really reads it is
counted at its own site. With one of these operators in between, that site does
not exist.

## Fix

Not a list of operators — the untraceable case itself. A column reference that did
not resolve is a value of unknown origin; if a list can be hiding in its type, refuse.

- `CanContainList` (new): true for LIST / ARRAY / MAP, walks STRUCT children and
  UNION members, and falls back to `LogicalType::IsNested()` so an unknown nested
  type errs toward refusing.
- `ContainerReadScanner::Scan`: after a failed resolve, an unresolved
  `BOUND_COLUMN_REF` whose type can contain a list raises `illegal`.
- `SafeToTruncate` result bindings: an output that did not resolve refuses when its
  type can contain a list; bindings/types length mismatch refuses outright.
- `forwarding` untouched — it skips only when the path *does* resolve, so the new
  check is reached through the same fall-through. Removing it would refuse q6.

A recursive CTE was never named anywhere in the fix and is refused by it, which is
the point of doing it this way.

## Measurements — TPC-H SF1, `sum(len(o.o_lineitems))` over the q6 predicate

`n` (row count) is identical everywhere; only the list lengths differ.

| case | shape | appended:o_lineitems | before (off / on) | after (off / on) |
|---|---|---|---|---|
| C0 | read whole, same query | 0 → 0 | 571,126 / 571,126 | 571,126 / 571,126 |
| C1 | MATERIALIZED CTE | **114,160 → 0** | 571,126 / **165,582** | 571,126 / 571,126 |
| C2 | inline CTE, 2 refs | **114,160 → 0** | 1,142,252 / **331,164** | 1,142,252 / 1,142,252 |
| U1 | UNION ALL, one branch | **114,160 → 0** | 571,286 / **165,742** | 571,286 / 571,286 |
| U2 | UNION ALL, both branches | **228,239 → 0** | 1,141,517 / **330,173** | 1,141,517 / 1,141,517 |
| R1 | recursive CTE | **114,160 → 0** | 571,126 / **165,582** | 571,126 / 571,126 |
| q6 | control | 114,160 → 114,160 | — | unchanged |

U1's `elements_appended:c_orders` went 160 → 0. That second branch was never at
risk: it is over-refusal, the expected cost of keying on the untraceable value
rather than on which spec it endangers.

Shapes that were already caught and still are, all appended 0 and results equal
before and after: lambda (`list_filter`), list indexing, GROUP BY, correlated
subquery, and a read above a window. A window passes its input columns through
under the child's bindings, so that one resolves and is caught the ordinary way.

## Regression

- 27 nested TPC-H queries: `elements_decoded` / `elements_appended` identical to
  `results/2026-09-19/duckdb_counters.tsv`, all 27 rows, re-measured with
  `scripts/bench_prenest_counters.sh`. No query lost a pushdown.
- 27 query results: identical between `parquet_prenest_auto` false and true
  (EXCEPT ALL both directions, 0 rows each).
- `test/sql/optimizer/prenest/*` 578 assertions, `parquet_prenest_filter.test` 35,
  `prenest_nested_projection.test` 34 — all pass.
- The new test file fails on the pre-fix source (stops at the MATERIALIZED CTE case).

## Known gaps

- Over-refusal: any untraceable list-shaped value anywhere in a plan refuses every
  spec of that query. Not measured on a workload that has one outside these probes.
- `LOGICAL_DELIM_GET` with a list-typed correlated column is covered by the same
  rule but was not measured — the correlated subquery probe correlates on a scalar.
