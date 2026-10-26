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

---

# Schema-shape coverage (same day, same machine)

Local WSL2, build from `753246123e`, `PRAGMA disable_verification`.
Commit: **`fd99dae38f`** — `test/sql/optimizer/prenest/prenest_schema_shapes.test`.

Eleven shapes the other test files never build. Every non-zero expected counter comes
from counting the passing elements with the pass OFF, not from what the pass produced.

| case | shape | independent count (off) | appended (on) | verdict |
|---|---|---|---|---|
| s1 | 3 levels, predicate innermost | 25 | `:c` 25 | pushes |
| s2a | `Orders[].LineItems[].Qty`, query same case | 23 | `:LineItems` 23 | pushes |
| s2b | same file, query all lower case | 23 | `:LineItems` 23 | pushes |
| s3a | column literally named `"a.b"` | 1 | 0 | **optimizer refuses** |
| s3b | struct `a` field `b` in the same file | 1 | 0 | **reader refuses** |
| s4a | two files, same shape, one scan | 23 | `:items` 23 | pushes |
| s4b | second file lacks the column (`union_by_name`) | 13 | `:items` 13 | pushes on the file that has it |
| s5 | siblings: `items` filtered, `tags` read whole | 23 | `:items` 23, `:tags` 0 | pushes |
| s6 | `LIST<INTEGER>` | 9 | 0 | refused - element is not a STRUCT |
| s7 | MAP beside the filtered list | 12 | `:items` 12 | pushes |
| s8 | 30k rows x 3, row groups of 5,000 | 54,000 | `:items` 54,000, carryovers 10 | pushes |

Vacuity check: all eight non-zero counters read **0** with `parquet_prenest_auto=false`.

## What the shapes settled

- **Letter case.** The path is rendered from the scan's own column names and the element
  struct's field names, never from how the query spelled them, so `s2a` and `s2b` produce
  the same spec and the same counter key. The case-insensitive `CountPathMatches`
  (`parquet_reader.cpp:454`) is therefore not load-bearing here; the exact `by_path` lookup
  at 560 hits either way. A spec whose spelling differed from the file's would pass 543 and
  then never be found at 560 - no such producer exists on the optimizer path.
- **Dotted names, refused at two different stages.** `s3a` and `s3b` are the same file and
  both end at 0, but not in the same place. `s3a` never gets a spec (`EXPLAIN` shows no
  `Pre-nest Filters`): the target round-tripped through `RenderPath`/`ParsePath` into two
  steps, no UNNEST matched it, and `SafeToTruncate`'s `iterated` lookup came up empty. `s3b`
  does get a spec and the reader drops it, because two schema nodes render to `"a.b"`. This
  confirms by measurement what was previously a code-reading conclusion.
- **MAP nodes** are counted as list paths (`parquet_reader.cpp:443`), so `s7`'s file has two.
  They render differently from the target, so the uniqueness check still sees exactly one.
- **Multi-file.** A spec is resolved per file against that file's schema, so a file without
  the path simply keeps the stock read (`s4b`).

## Note carried over

`s8` asserts `carryovers > 0` but deliberately not `elements_decoded`: that counter
undercounts by `row_groups x STANDARD_VECTOR_SIZE`, because `ListColumnReader::ApplyPendingSkips`
lacks the `pending_skips == 0` guard its base class has and the zero-length skip read it then
performs is not counted. `elements_appended` is exact - it matched the independent count in
every case above.

## Open item found while writing these

`PRAGMA enable_verification` also sets `verify_serializer`, and `ParquetOptionsSerialization`
does not carry `prenest_filters`, so the plan that actually executes comes back from the
round trip with no spec and the pass is silently off. Measured on TPC-H q6:
`elements_appended:o_lineitems` **0** under `enable_verification`, **114,160** under
`disable_verification`. Affected existing assertions: `prenest_nested_projection.test` (whole
file), `prenest_deep_safety.test:13-103`, `prenest_multi_spec.test:13-69`. Not changed here.

---

# Follow-ups (2026-09-29, local WSL2)

Commits, in order: **`4533f24462`** (comments), **`a4e038866a`** (test s9),
**`723e557d66`** (spec serialization), **`d21662a89e`** (skip-path counting),
**`00bdbb0221`** (`parquet_prenest_lists()`), **`4f07424e4e`** (optimizer counters).

## Spec serialization (`723e557d66`)

`PRAGMA enable_verification` sets `verify_serializer`, `Planner::VerifyPlan` round-trips the
plan and REPLACES it, and `ParquetOptionsSerialization` did not carry `prenest_filters`. The
plan that ran had no spec, so the pass was off. `parquet.json` now has entries for
`PrenestRawCondition` and `PrenestFilterSpec` and member 108 on `ParquetOptionsSerialization`;
regenerated with the script, not hand-edited.

```
q6, PRAGMA enable_verification      before  elements_appended:o_lineitems = 0
                                    after                                 = 684,960
```

684,960 is 6 x 114,160 - verification runs the query repeatedly and the counters are
process-global, so `> 0` is the assertion, as intended.

The three regions that had been asserting against a pass that never ran now exercise it,
checked with a representative query of each shape under `enable_verification`:

| region | shape | appended |
|---|---|---|
| `prenest_deep_safety.test:13-103` | inner list filtered | `items` 138 (= 23 x 6) |
| `prenest_multi_spec.test:13-69` | two specs in one scan | `orders` 48, `items` 138 |
| `prenest_nested_projection.test` (whole file) | single-level predicate | `posts` 48 |

## elements_decoded (`d21662a89e`)

`ApplyPendingSkips` is upstream (`08b3e8665a`, `289d906015`), so its behaviour is untouched and
only the counting moved: `ReadInternal` counts its child read when the reader carries a pre-nest
filter. Guarded on the filter, so a plain read still counts nothing and `auto=false` is the same
baseline.

The counter is now exact. Checked against the true slot count of every list:

```
c_orders                1,550,004      r_nations        25
c_orders[].o_lineitems  6,051,219      s_partsupps  800,000
```

and against all 27 queries, where `decoded` = the sum over (scan x filtered list) of that
list's slots. 25 of 27 match the sum of the paths in `parquet_prenest_lists()` directly; q7 and
q11 read `region` **twice**, so `r_nations` decodes twice (50) while the path set lists it once.
With that accounted for, **all 27 match**.

`elements_appended` is unchanged: all 27 identical to `results/2026-09-19/duckdb_counters.tsv`.
`decoded` differing from that file is expected and is what this change is.

## parquet_prenest_lists() (`00bdbb0221`)

`<counter>:<name>` answers 0 for a name it never saw, so a refused list, a list nobody asked
for, and a typo all read the same. The new function returns the list PATHS the reader was asked
to filter since the last reset, sorted and comma-joined, registered before the uniqueness check
so a refused spec still shows. It is a separate function rather than
`parquet_prenest_stat('lists')` because that one returns BIGINT and four existing assertions
compare it with `> 0`.

It separates two of the three cases, not all three:

| | in `lists` | `:<name>` |
|---|---|---|
| asked for, reader refused (`s3b`) | yes (`a.b`) | 0 |
| optimizer never asked (`s3a`, `s5`'s `tags`) | no | 0 |
| typo | no | 0 |

Tests updated to assert it alongside the existing `:<name>` assertions:
`prenest_untraceable_reads.test` (all 11 refusals empty, control `orders[].items`),
`prenest_schema_shapes.test` (s3a empty, s3b `a.b`, s5 `o[].items`, s6 empty),
`prenest_boundary_shapes.test` (case 6 `orders`).

Also corrected a wrong comment written earlier: `PrenestReaderPlan::by_path` is a
`case_insensitive_map_t`, so the claim that s2b depends on an exact lookup there was wrong.

## Optimizer counters (`4f07424e4e`)

`PrenestPushdownTotals` accumulates instead of being assigned whole, so reading it with a plain
SELECT no longer zeroes it - that SELECT's own run contributes nothing. The
turn-the-pass-off-first protocol is gone. Read as `parquet_prenest_stat('opt:<name>')`.

Cross-check against the eight queries pre-nest never improves:

```
q2 q9 q9b q13 q16 q17 q18 q22   every counter 0, including binders_not_formable
                                 and refused_list_read_elsewhere
q6 (contrast)                    formed 3, levels_lifted 3, specs_pushed 1,
                                 absorbed_at_scan 1, nothing declined
```

So it is not that the pass tried and declined on those eight - there is no element-level
predicate on an UNNEST for it to classify. That matches the earlier EXPLAIN reading, now stated
by the pass itself.

## Regression

- 27 queries: `elements_appended` identical to `results/2026-09-19/duckdb_counters.tsv`, all 27.
  Results identical between `parquet_prenest_auto` false and true.
- `test/sql/optimizer/prenest/*` 707 assertions over 10 files, `parquet_prenest_filter.test` 35,
  `prenest_nested_projection.test` 34 - all pass.

## Not done, on purpose

The duplicate check the carry-over performs, and widening `StripLeftovers` past Filters.
