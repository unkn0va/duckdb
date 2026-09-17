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
