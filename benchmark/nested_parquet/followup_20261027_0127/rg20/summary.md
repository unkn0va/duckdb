# Nested Parquet benchmark: builtin / flat

builtin = the original DuckDB (`base`), flat = `read_parquet_flat` of main_rey (`final`; XMark: the flat_minmax form). Ratio = builtin seconds / flat seconds (> 1: flat is faster); fastest of the runs.

## Per dataset and thread count (geometric mean over the queries)

| dataset | threads=1 | threads=20 |
|---|---|---|
| TPC-H SF1 | 12.40x | 6.47x |
| Selectivity (A), a % N = 0 | 0.61x | 0.69x |
| Selectivity (B), a < 10^6 / N | 0.12x | 0.36x |

## Per query

Seconds: builtin / flat = ratio.

### TPC-H SF1

| query | threads=1 | threads=20 |
|---|---|---|
| q01 | 5.311 / 0.648 = **8.20x** | 1.662 / 0.155 = **10.72x** |
| q03 | 4.949 / 0.423 = **11.70x** | 1.559 / 0.370 = **4.21x** |
| q04 | 4.960 / 0.337 = **14.72x** | 1.534 / 0.308 = **4.98x** |
| q06 | 4.957 / 0.327 = **15.16x** | 1.472 / 0.104 = **14.15x** |
| q10 | 4.892 / 0.428 = **11.43x** | 1.563 / 0.387 = **4.04x** |
| q12 | 5.157 / 0.347 = **14.86x** | 1.533 / 0.269 = **5.70x** |

### Selectivity (A), a % N = 0

| query | threads=1 | threads=20 |
|---|---|---|
| N = 1 | 0.258 / 0.291 = **0.89x** | 0.032 / 0.061 = **0.52x** |
| N = 10^1 | 0.166 / 0.203 = **0.82x** | 0.024 / 0.034 = **0.71x** |
| N = 10^2 | 0.155 / 0.193 = **0.80x** | 0.026 / 0.032 = **0.81x** |
| N = 10^3 | 0.155 / 0.187 = **0.83x** | 0.023 / 0.031 = **0.74x** |
| N = 10^4 | 0.160 / 0.186 = **0.86x** | 0.022 / 0.030 = **0.73x** |
| N = 10^5 | 0.059 / 0.187 = **0.32x** | 0.021 / 0.028 = **0.75x** |
| N = 10^6 | 0.044 / 0.186 = **0.24x** | 0.016 / 0.027 = **0.59x** |

### Selectivity (B), a < 10^6 / N

| query | threads=1 | threads=20 |
|---|---|---|
| N = 1 | 0.224 / 0.270 = **0.83x** | 0.030 / 0.057 = **0.53x** |
| N = 10^1 | 0.043 / 0.177 = **0.24x** | 0.023 / 0.032 = **0.72x** |
| N = 10^2 | 0.014 / 0.162 = **0.09x** | 0.012 / 0.026 = **0.46x** |
| N = 10^3 | 0.010 / 0.161 = **0.06x** | 0.007 / 0.027 = **0.26x** |
| N = 10^4 | 0.010 / 0.161 = **0.06x** | 0.007 / 0.026 = **0.27x** |
| N = 10^5 | 0.011 / 0.162 = **0.07x** | 0.007 / 0.026 = **0.27x** |
| N = 10^6 | 0.011 / 0.161 = **0.07x** | 0.007 / 0.027 = **0.26x** |

## Three binaries: original DuckDB, prenest-3way, main_rey

`base` = builtin query of the original DuckDB, `prenest` = the same builtin query with prenest-3way (parquet_prenest_auto = true), `prenestoff` = prenest-3way with parquet_prenest_auto = false (still with its LIST<STRUCT> pruning), flat = `read_parquet_flat` of main_rey (`final`). Ratio = base seconds / seconds of the column (> 1: faster than the original DuckDB); geometric mean over the queries, without those listed below the table.

| dataset | threads | base / prenest | base / prenestoff | base / flat (final) |
|---|---|---|---|---|
| TPC-H SF1 | 1 | 4.77x | 1.66x | 12.40x |
| TPC-H SF1 | 20 | 4.42x | 1.65x | 6.47x |
| Selectivity (A), a % N = 0 | 1 | 0.95x | 0.94x | 0.61x |
| Selectivity (A), a % N = 0 | 20 | 1.00x | 1.01x | 0.69x |
| Selectivity (B), a < 10^6 / N | 1 | 1.06x | 1.12x | 0.12x |
| Selectivity (B), a < 10^6 / N | 20 | 1.03x | 0.97x | 0.36x |

### Per query (seconds)

| dataset | query | threads | base | prenest | prenestoff | flat (final) |
|---|---|---|---|---|---|---|
| TPC-H SF1 | q01 | 1 | 5.311 | 3.240 | 3.453 | 0.648 |
| TPC-H SF1 | q01 | 20 | 1.662 | 1.083 | 0.983 | 0.155 |
| TPC-H SF1 | q03 | 1 | 4.949 | 1.733 | 2.875 | 0.423 |
| TPC-H SF1 | q03 | 20 | 1.559 | 0.536 | 0.928 | 0.370 |
| TPC-H SF1 | q04 | 1 | 4.960 | 0.729 | 2.811 | 0.337 |
| TPC-H SF1 | q04 | 20 | 1.534 | 0.241 | 0.890 | 0.308 |
| TPC-H SF1 | q06 | 1 | 4.957 | 0.617 | 3.002 | 0.327 |
| TPC-H SF1 | q06 | 20 | 1.472 | 0.206 | 0.917 | 0.104 |
| TPC-H SF1 | q10 | 1 | 4.892 | 0.875 | 2.962 | 0.428 |
| TPC-H SF1 | q10 | 20 | 1.563 | 0.267 | 1.009 | 0.387 |
| TPC-H SF1 | q12 | 1 | 5.157 | 0.630 | 3.126 | 0.347 |
| TPC-H SF1 | q12 | 20 | 1.533 | 0.243 | 0.939 | 0.269 |
| Selectivity (A), a % N = 0 | N = 1 | 1 | 0.258 | 0.258 | 0.250 | 0.291 |
| Selectivity (A), a % N = 0 | N = 1 | 20 | 0.032 | 0.033 | 0.035 | 0.061 |
| Selectivity (A), a % N = 0 | N = 10^1 | 1 | 0.166 | 0.163 | 0.170 | 0.203 |
| Selectivity (A), a % N = 0 | N = 10^1 | 20 | 0.024 | 0.025 | 0.025 | 0.034 |
| Selectivity (A), a % N = 0 | N = 10^2 | 1 | 0.155 | 0.164 | 0.203 | 0.193 |
| Selectivity (A), a % N = 0 | N = 10^2 | 20 | 0.026 | 0.026 | 0.024 | 0.032 |
| Selectivity (A), a % N = 0 | N = 10^3 | 1 | 0.155 | 0.197 | 0.195 | 0.187 |
| Selectivity (A), a % N = 0 | N = 10^3 | 20 | 0.023 | 0.024 | 0.025 | 0.031 |
| Selectivity (A), a % N = 0 | N = 10^4 | 1 | 0.160 | 0.169 | 0.152 | 0.186 |
| Selectivity (A), a % N = 0 | N = 10^4 | 20 | 0.022 | 0.022 | 0.022 | 0.030 |
| Selectivity (A), a % N = 0 | N = 10^5 | 1 | 0.059 | 0.058 | 0.059 | 0.187 |
| Selectivity (A), a % N = 0 | N = 10^5 | 20 | 0.021 | 0.018 | 0.018 | 0.028 |
| Selectivity (A), a % N = 0 | N = 10^6 | 1 | 0.044 | 0.045 | 0.043 | 0.186 |
| Selectivity (A), a % N = 0 | N = 10^6 | 20 | 0.016 | 0.017 | 0.015 | 0.027 |
| Selectivity (B), a < 10^6 / N | N = 1 | 1 | 0.224 | 0.223 | 0.229 | 0.270 |
| Selectivity (B), a < 10^6 / N | N = 1 | 20 | 0.030 | 0.032 | 0.033 | 0.057 |
| Selectivity (B), a < 10^6 / N | N = 10^1 | 1 | 0.043 | 0.039 | 0.042 | 0.177 |
| Selectivity (B), a < 10^6 / N | N = 10^1 | 20 | 0.023 | 0.025 | 0.029 | 0.032 |
| Selectivity (B), a < 10^6 / N | N = 10^2 | 1 | 0.014 | 0.013 | 0.011 | 0.162 |
| Selectivity (B), a < 10^6 / N | N = 10^2 | 20 | 0.012 | 0.009 | 0.011 | 0.026 |
| Selectivity (B), a < 10^6 / N | N = 10^3 | 1 | 0.010 | 0.008 | 0.011 | 0.161 |
| Selectivity (B), a < 10^6 / N | N = 10^3 | 20 | 0.007 | 0.006 | 0.008 | 0.027 |
| Selectivity (B), a < 10^6 / N | N = 10^4 | 1 | 0.010 | 0.011 | 0.009 | 0.161 |
| Selectivity (B), a < 10^6 / N | N = 10^4 | 20 | 0.007 | 0.006 | 0.007 | 0.026 |
| Selectivity (B), a < 10^6 / N | N = 10^5 | 1 | 0.011 | 0.010 | 0.008 | 0.162 |
| Selectivity (B), a < 10^6 / N | N = 10^5 | 20 | 0.007 | 0.009 | 0.006 | 0.026 |
| Selectivity (B), a < 10^6 / N | N = 10^6 | 1 | 0.011 | 0.011 | 0.009 | 0.161 |
| Selectivity (B), a < 10^6 / N | N = 10^6 | 20 | 0.007 | 0.007 | 0.007 | 0.027 |

