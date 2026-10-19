Smallest of 5 processes per binary, each running the query 3 times with 1 thread. Ratios: b / a1.

| query | instructions a1 | instructions b | cycles a1 | cycles b | instructions b/a1 | cycles b/a1 | IPC a1 | IPC b |
|---|---|---|---|---|---|---|---|---|
| tpch_sf1/q06.flat | 9.352e+09 | 9.34e+09 | 3.39e+09 | 3.045e+09 | 0.9988 | 0.8980 | 2.758 | 3.068 |
| tpch_sf1/q12.flat | 9.28e+09 | 9.278e+09 | 3.535e+09 | 3.268e+09 | 0.9998 | 0.9244 | 2.625 | 2.839 |
| xmark/q02.flat_minmax | 1.531e+09 | 1.53e+09 | 7.442e+08 | 7.079e+08 | 0.9991 | 0.9512 | 2.057 | 2.161 |
| selectivity_random/n6.flat | 4.694e+09 | 4.693e+09 | 1.838e+09 | 1.693e+09 | 0.9997 | 0.9210 | 2.555 | 2.773 |
| selectivity_sorted/n1.flat | 5.035e+09 | 5.034e+09 | 1.862e+09 | 1.733e+09 | 0.9997 | 0.9312 | 2.705 | 2.904 |
| tpch_sf1/q06.builtin | 7.87e+10 | 7.87e+10 | 4.421e+10 | 4.251e+10 | 1.0000 | 0.9616 | 1.780 | 1.851 |
| xmark/q02.builtin | 9.392e+09 | 9.392e+09 | 5.249e+09 | 5.179e+09 | 0.9999 | 0.9866 | 1.789 | 1.814 |
| dblp/q08.builtin | 2.459e+10 | 2.457e+10 | 1.329e+10 | 1.323e+10 | 0.9992 | 0.9952 | 1.850 | 1.858 |
| selectivity_random/n6.builtin | 6.618e+08 | 6.618e+08 | 4.703e+08 | 4.506e+08 | 1.0001 | 0.9581 | 1.407 | 1.469 |
