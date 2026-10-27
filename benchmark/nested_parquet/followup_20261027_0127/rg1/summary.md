# Nested Parquet benchmark: builtin / flat

builtin = the original DuckDB (`base`), flat = `read_parquet_flat` of main_rey (`final`; XMark: the flat_minmax form). Ratio = builtin seconds / flat seconds (> 1: flat is faster); fastest of the runs.

## Per dataset and thread count (geometric mean over the queries)

| dataset | threads=1 | threads=20 |
|---|---|---|
| TPC-H SF1 | 15.20x | 34.08x |
| XMark | 6.53x | 4.77x |
| Selectivity (A), a % N = 0 | 0.74x | 3.23x |
| Selectivity (B), a < 10^6 / N | 0.41x | 1.28x |

## Per query

Seconds: builtin / flat = ratio.

### TPC-H SF1

| query | threads=1 | threads=20 |
|---|---|---|
| q01 | 6.496 / 0.645 = **10.07x** | 6.451 / 0.147 = **43.88x** |
| q03 | 5.978 / 0.425 = **14.07x** | 5.873 / 0.255 = **23.03x** |
| q04 | 5.918 / 0.330 = **17.93x** | 6.178 / 0.160 = **38.61x** |
| q06 | 6.218 / 0.335 = **18.56x** | 6.220 / 0.106 = **58.68x** |
| q10 | 6.076 / 0.429 = **14.16x** | 5.984 / 0.391 = **15.30x** |
| q12 | 6.312 / 0.342 = **18.46x** | 6.166 / 0.138 = **44.68x** |

### XMark

| query | threads=1 | threads=20 |
|---|---|---|
| q02 (flat_minmax) | 0.465 / 0.063 = **7.38x** | 0.463 / 0.083 = **5.58x** |
| q03 (flat_minmax) | 0.479 / 0.118 = **4.06x** | 0.472 / 0.163 = **2.90x** |
| q04 (flat_minmax) | 0.485 / 0.059 = **8.22x** | 0.468 / 0.081 = **5.78x** |
| q04p (flat_minmax) | 0.487 / 0.066 = **7.38x** | 0.479 / 0.086 = **5.57x** |

### Selectivity (A), a % N = 0

| query | threads=1 | threads=20 |
|---|---|---|
| N = 1 | 0.315 / 0.281 = **1.12x** | 0.279 / 0.075 = **3.72x** |
| N = 10^1 | 0.181 / 0.200 = **0.90x** | 0.182 / 0.050 = **3.64x** |
| N = 10^2 | 0.156 / 0.179 = **0.87x** | 0.202 / 0.045 = **4.49x** |
| N = 10^3 | 0.163 / 0.183 = **0.89x** | 0.162 / 0.046 = **3.52x** |
| N = 10^4 | 0.112 / 0.183 = **0.61x** | 0.165 / 0.050 = **3.30x** |
| N = 10^5 | 0.113 / 0.183 = **0.62x** | 0.136 / 0.045 = **3.02x** |
| N = 10^6 | 0.072 / 0.182 = **0.40x** | 0.075 / 0.044 = **1.70x** |

### Selectivity (B), a < 10^6 / N

| query | threads=1 | threads=20 |
|---|---|---|
| N = 1 | 0.225 / 0.259 = **0.87x** | 0.244 / 0.078 = **3.13x** |
| N = 10^1 | 0.073 / 0.183 = **0.40x** | 0.063 / 0.047 = **1.34x** |
| N = 10^2 | 0.066 / 0.172 = **0.38x** | 0.047 / 0.045 = **1.04x** |
| N = 10^3 | 0.059 / 0.177 = **0.33x** | 0.041 / 0.046 = **0.89x** |
| N = 10^4 | 0.058 / 0.172 = **0.34x** | 0.062 / 0.045 = **1.38x** |
| N = 10^5 | 0.065 / 0.176 = **0.37x** | 0.043 / 0.046 = **0.93x** |
| N = 10^6 | 0.063 / 0.170 = **0.37x** | 0.052 / 0.046 = **1.13x** |

## Three binaries: original DuckDB, prenest-3way, main_rey

`base` = builtin query of the original DuckDB, `prenest` = the same builtin query with prenest-3way (parquet_prenest_auto = true), `prenestoff` = prenest-3way with parquet_prenest_auto = false (still with its LIST<STRUCT> pruning), flat = `read_parquet_flat` of main_rey (`final`). Ratio = base seconds / seconds of the column (> 1: faster than the original DuckDB); geometric mean over the queries, without those listed below the table.

| dataset | threads | base / prenest | base / prenestoff | base / flat (final) |
|---|---|---|---|---|
| TPC-H SF1 | 1 | 5.57x | 1.75x | 15.20x |
| TPC-H SF1 | 20 | 5.50x | 1.73x | 34.08x |
| XMark | 1 | 3.58x | 3.58x | 6.53x |
| XMark | 20 | 3.50x | 3.53x | 4.77x |
| Selectivity (A), a % N = 0 | 1 | 1.03x | 0.98x | 0.74x |
| Selectivity (A), a % N = 0 | 20 | 1.17x | 1.16x | 3.23x |
| Selectivity (B), a < 10^6 / N | 1 | 0.97x | 1.00x | 0.41x |
| Selectivity (B), a < 10^6 / N | 20 | 1.00x | 0.96x | 1.28x |

### Per query (seconds)

| dataset | query | threads | base | prenest | prenestoff | flat (final) |
|---|---|---|---|---|---|---|
| TPC-H SF1 | q01 | 1 | 6.496 | 3.750 | 3.954 | 0.645 |
| TPC-H SF1 | q01 | 20 | 6.451 | 3.779 | 4.009 | 0.147 |
| TPC-H SF1 | q03 | 1 | 5.978 | 1.872 | 3.316 | 0.425 |
| TPC-H SF1 | q03 | 20 | 5.873 | 1.899 | 3.323 | 0.255 |
| TPC-H SF1 | q04 | 1 | 5.918 | 0.734 | 3.355 | 0.330 |
| TPC-H SF1 | q04 | 20 | 6.178 | 0.734 | 3.312 | 0.160 |
| TPC-H SF1 | q06 | 1 | 6.218 | 0.643 | 3.428 | 0.335 |
| TPC-H SF1 | q06 | 20 | 6.220 | 0.653 | 3.489 | 0.106 |
| TPC-H SF1 | q10 | 1 | 6.076 | 0.868 | 3.444 | 0.429 |
| TPC-H SF1 | q10 | 20 | 5.984 | 0.877 | 3.542 | 0.391 |
| TPC-H SF1 | q12 | 1 | 6.312 | 0.639 | 3.680 | 0.342 |
| TPC-H SF1 | q12 | 20 | 6.166 | 0.643 | 3.669 | 0.138 |
| XMark | q02 | 1 | 0.465 | 0.120 | 0.118 | 0.063 |
| XMark | q02 | 20 | 0.463 | 0.119 | 0.118 | 0.083 |
| XMark | q03 | 1 | 0.479 | 0.138 | 0.139 | 0.118 |
| XMark | q03 | 20 | 0.472 | 0.137 | 0.137 | 0.163 |
| XMark | q04 | 1 | 0.485 | 0.133 | 0.136 | 0.059 |
| XMark | q04 | 20 | 0.468 | 0.137 | 0.134 | 0.081 |
| XMark | q04p | 1 | 0.487 | 0.145 | 0.144 | 0.066 |
| XMark | q04p | 20 | 0.479 | 0.146 | 0.146 | 0.086 |
| Selectivity (A), a % N = 0 | N = 1 | 1 | 0.315 | 0.291 | 0.317 | 0.281 |
| Selectivity (A), a % N = 0 | N = 1 | 20 | 0.279 | 0.274 | 0.267 | 0.075 |
| Selectivity (A), a % N = 0 | N = 10^1 | 1 | 0.181 | 0.181 | 0.186 | 0.200 |
| Selectivity (A), a % N = 0 | N = 10^1 | 20 | 0.182 | 0.200 | 0.197 | 0.050 |
| Selectivity (A), a % N = 0 | N = 10^2 | 1 | 0.156 | 0.174 | 0.167 | 0.179 |
| Selectivity (A), a % N = 0 | N = 10^2 | 20 | 0.202 | 0.151 | 0.159 | 0.045 |
| Selectivity (A), a % N = 0 | N = 10^3 | 1 | 0.163 | 0.118 | 0.150 | 0.183 |
| Selectivity (A), a % N = 0 | N = 10^3 | 20 | 0.162 | 0.121 | 0.178 | 0.046 |
| Selectivity (A), a % N = 0 | N = 10^4 | 1 | 0.112 | 0.118 | 0.118 | 0.183 |
| Selectivity (A), a % N = 0 | N = 10^4 | 20 | 0.165 | 0.134 | 0.101 | 0.050 |
| Selectivity (A), a % N = 0 | N = 10^5 | 1 | 0.113 | 0.111 | 0.110 | 0.183 |
| Selectivity (A), a % N = 0 | N = 10^5 | 20 | 0.136 | 0.096 | 0.092 | 0.045 |
| Selectivity (A), a % N = 0 | N = 10^6 | 1 | 0.072 | 0.076 | 0.077 | 0.182 |
| Selectivity (A), a % N = 0 | N = 10^6 | 20 | 0.075 | 0.074 | 0.070 | 0.044 |
| Selectivity (B), a < 10^6 / N | N = 1 | 1 | 0.225 | 0.254 | 0.192 | 0.259 |
| Selectivity (B), a < 10^6 / N | N = 1 | 20 | 0.244 | 0.232 | 0.208 | 0.078 |
| Selectivity (B), a < 10^6 / N | N = 10^1 | 1 | 0.073 | 0.073 | 0.074 | 0.183 |
| Selectivity (B), a < 10^6 / N | N = 10^1 | 20 | 0.063 | 0.065 | 0.069 | 0.047 |
| Selectivity (B), a < 10^6 / N | N = 10^2 | 1 | 0.066 | 0.066 | 0.065 | 0.172 |
| Selectivity (B), a < 10^6 / N | N = 10^2 | 20 | 0.047 | 0.050 | 0.047 | 0.045 |
| Selectivity (B), a < 10^6 / N | N = 10^3 | 1 | 0.059 | 0.063 | 0.065 | 0.177 |
| Selectivity (B), a < 10^6 / N | N = 10^3 | 20 | 0.041 | 0.047 | 0.065 | 0.046 |
| Selectivity (B), a < 10^6 / N | N = 10^4 | 1 | 0.058 | 0.062 | 0.064 | 0.172 |
| Selectivity (B), a < 10^6 / N | N = 10^4 | 20 | 0.062 | 0.044 | 0.069 | 0.045 |
| Selectivity (B), a < 10^6 / N | N = 10^5 | 1 | 0.065 | 0.063 | 0.061 | 0.176 |
| Selectivity (B), a < 10^6 / N | N = 10^5 | 20 | 0.043 | 0.044 | 0.041 | 0.046 |
| Selectivity (B), a < 10^6 / N | N = 10^6 | 1 | 0.063 | 0.063 | 0.063 | 0.170 |
| Selectivity (B), a < 10^6 / N | N = 10^6 | 20 | 0.052 | 0.059 | 0.043 | 0.046 |

