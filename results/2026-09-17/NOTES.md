# Measurement notes — 2026-09-17, apache10

## Caveats
- **q9**: DataFusion uses the part-first join order (commit "Fix q9 join order");
  DuckDB uses the original FROM order. Both ratio ~0.97, so no impact on conclusions.
- **q13 / q22**: DataFusion is 10-20x slower than flatread here due to the
  `union all` that re-adds empty-`c_orders` customers. Compare ratios only,
  never absolute times across engines.
- **Query sets**: common 22 (q1..q22). DuckDB additionally has q3a q3b q9b q10a q10b
  (predicate-placement variants); DataFusion has no counterparts.
- **elements_decoded** is unreliable at small scale (observed DEC=0 with
  carryovers=0 on a 360-element fixture). Stable at TPC-H scale. Use
  elements_appended as the ground truth; it matches independent counts.
- Absolute times include process startup (~50-100ms), so ratios for sub-0.2s
  queries (q2 q11 q16) are compressed.

## Not ported
- 4.5 Filtered UNNEST (UnnestFilter). 16 queries still carry 1-2 residual
  comprehensions on UNNEST.
- IN extraction via ConjunctionOrFilter + ConstantFilter(EQUAL). Reader already
  supports it; blocked in PrenestRawCondition / ToRawConditions / Bind.
  Measured headroom: q19 retain 1,500,048 -> 214,377 (7.0x).

## Corrections to the above (2026-09-17, Layun, after 53a3124db8)

- **"16 queries still carry 1-2 residual comprehensions"** — that count was taken
  through `EXPLAIN`, which changes what this pass does (see below). Executed, the
  figure at ea57efbb72 was **11 queries / 14 comprehensions**. After multiple specs
  per scan it is **8 comprehensions in 5 queries** (q4, q7, q12, q19, q21), all of
  them inexpressible as `<field> <cmp> <literal>` — field-to-field comparisons and
  OR/IN lists — and none blocked by the interface any more.
- **q3/q3a/q3b and q10/q10a/q10b ratios here are pre-multi-spec.** They were
  measured with only the inner `c_orders[].o_lineitems` spec pushed. Both families
  now push a second spec on the outer `c_orders` list (1500000 -> 727305 and
  1500000 -> 57069 elements appended), so the times in this directory no longer
  describe the current code and have to be re-measured on apache10.


## elements_decoded is unreliable at small scale

`elements_decoded` is incremented only on the non-carryover read path
(`ListColumnReader::ReadFilteredInternal`), so on a file small enough that every list fits in one
child read it stays 0 even though the filter ran. Assert on `elements_appended` /
`predicate_elements` instead. At SF1 it is stable and usable (q6/q12: 6045075).

## EXPLAIN changes the optimizer's decisions — do not measure through it

`PrenestFilterPushdown::SafeToTruncate` walks `root->GetColumnBindings()` to check whether the
plan's own output reads the target list or a value containing it. Under `EXPLAIN` the plan root is
`LogicalExplain`, whose `GetColumnBindings()` returns the synthetic bindings `(0,0)` and `(0,1)`.
`ResolveBindingPath` takes `table_index == 0` at face value, finds whatever operator happens to
carry table index 0 — in a single-scan plan, the `LogicalGet` — and resolves the binding to that
scan's first column. That column is usually an ancestor of the target list, so the safety check
refuses.

Repro (SF1 nested customer):

    SET parquet_prenest_auto=true;
    PRAGMA explain_output='optimized_only';
    EXPLAIN SELECT sum(l.l_extendedprice * l.l_discount) FROM (
      SELECT unnest(o.o_lineitems) AS l
      FROM (SELECT unnest(c_orders) AS o FROM '<customer.parquet>') os
    ) WHERE l.l_shipdate >= '1994-01-01';

The same statement without `EXPLAIN` pushes a spec for `c_orders[].o_lineitems`; with `EXPLAIN` it
pushes nothing, although the query outputs only a scalar aggregate and reads no list whole.

Consequences:
  * Every pre-nest measurement must come from **executing** the query, never from `EXPLAIN`. A
    sweep taken through `EXPLAIN` reports far more residual comprehensions than really exist
    (16 queries / 28 comprehensions vs. 11 / 14 on 2026-09-17, ea57efbb72).
  * Plan-shape assertions (`EXPLAIN ... REGEX`) cannot be used to test this pass at all, because
    the pass behaves differently under the statement being asserted on.

Direction of the bug is "refuse", so it costs optimization, never correctness. Fix is separate:
`ResolveBindingPath` should reject a binding whose table index it did not itself collect as a
PROJECTION / UNNEST / GET, rather than trusting the index.

## The reader matches a spec to a list by bare name

`PrenestFilterSpec::list_name` is the last path segment (`LastSegment`), and
`TryBuildPrenestFilter` attaches a spec to every parquet schema node with that name. A schema that
reuses a list name at two depths (e.g. top-level `items` and `orders[].items`) therefore has one
spec applied to both lists. Pre-existing, reachable from the manual `parquet_prenest_filter`
setting as well as from the automatic path; not exercised by TPC-H, which has no name collision.
The optimizer's collision guard (`DropNameCollisions`) only covers the case where two specs of one
scan collide, not a single spec whose bare name is ambiguous against the file schema. Real fix is
to carry the full root-relative path in the spec and match on it.

## Path encoding is not injective (recorded 2026-09-18)

`RenderPath` joins segments with `.` and marks element steps with `[]`.
When a field name itself contains `.` or `[]`, distinct nodes render to the
same string:

- column `"a.b"` (LIST) vs field `b` of struct `a` (LIST) -> both render `a.b`
- column `"a[]"` (STRUCT) vs the element node of list `a` -> both render `a[]`

Handled by requiring a unique match in the reader: a spec is attached only
when its path matches exactly one LIST/MAP node in the file schema. Ambiguous
paths are refused (no pushdown, correct results, `elements_appended=0`).
Escaping the encoding was rejected because `SafeToTruncate` / `IsAncestorOrSame`
in the optimizer all depend on the current form.

The optimizer round-trip is separately broken for such names: `ParsePath("a.b")`
splits on `.` and yields two levels, so `SafeToTruncate`'s `iterated` lookup
misses. It fails in the safe direction (no spec), so it is left as is.

Fixed in cf84e2b368; regression cases in
`test/sql/optimizer/prenest/prenest_name_collision.test` (with controls proving
the refusal is the uniqueness check, not a missing spec).
