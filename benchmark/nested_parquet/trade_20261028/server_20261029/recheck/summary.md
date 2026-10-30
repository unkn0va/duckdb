| layout | dataset | queries | checks | failed |
|---|---|---|---|---|
| orig | dblp | 4 | 12 | 0 |
| orig | selectivity_random | 7 | 21 | 0 |
| orig | selectivity_sorted | 7 | 21 | 0 |
| orig | tpch_sf1 | 6 | 18 | 1 |
| orig | tpch_sf10 | 5 | 15 | 0 |
| orig | xmark | 4 | 12 | 0 |
| rg1 | selectivity_random | 7 | 21 | 0 |
| rg1 | selectivity_sorted | 7 | 21 | 0 |
| rg1 | tpch_sf1 | 6 | 18 | 1 |
| rg1 | xmark | 4 | 12 | 0 |
| rg20 | selectivity_random | 7 | 21 | 0 |
| rg20 | selectivity_sorted | 7 | 21 | 0 |
| rg20 | tpch_sf1 | 6 | 18 | 0 |

231 checks, 2 failed
- orig tpch_sf1 q01: flat_final_ok = False (reference: builtin of base)
- rg1 tpch_sf1 q01: flat_final_ok = False (reference: builtin of base)
