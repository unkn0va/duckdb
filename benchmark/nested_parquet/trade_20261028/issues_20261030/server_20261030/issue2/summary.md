# 이슈 2: join 예상 오류 (issue2)

```
date:     2026-10-30T08:53:04+00:00
host:     apache10, 40 hardware threads, 125 GiB memory
cpu:      Intel(R) Xeon(R) Gold 5215 CPU @ 2.50GHz
uptime:    08:53:04 up 1 day, 15:47,  3 users,  load average: 1.01, 1.97, 4.52
base:     v2.1.0-dev88383 a809d3cd51  /home/layun03/nested-bench/duckdb_base/build/release/duckdb
prenest:  v2.1.0-dev88385 fabde05fe6  /home/layun03/nested-bench/duckdb_prenest_base/build/release/duckdb
final:    v2.1.0-dev88410 2d6066fd4d  /home/layun03/nested-bench/duckdb_rey/build/release/duckdb
scripts:  d07a1fb8dd6 nested_parquet: trade issue 1, categories of the samples whose stack perf could not unwind
data:     /home/layun03/nested-bench/duckdb_rey/benchmark/nested_parquet/trade_20261028/data/full, earlier datasets /home/layun03/nested-bench/data
runs:     10 at 1 thread (variants), cardinality at 20 threads
```

## 2-1 실행 계획 변형 (1스레드, RUNS 중 최소, 초)

- fixed: `join_order`를 끄고 원소 → 부모 → 차원 표 순서로 씀(build 쪽은 build_side_probe_side가 정함). builtin·flat은 글이 같고 설정만 다름.
- preagg: 차원 표 join 앞에서 집계(q7_csa: c0, c1별 / q7_plots: c8별). q1, q6은 차원 표 join이 없어 해당 없음.
- 괄호: 원래 대비 배수(< 1이면 빠름). '=': 원래와 같은 실행 계획이라 다시 재지 않음. 결과: 모든 변형이 원래 쿼리(base builtin)와 같으면 yes.
- 계획: `variant_plans/<쿼리>.<변형>.<구성>.txt`

| 쿼리 | 구성 | orig | fixed | preagg | 결과 |
|---|---|---|---|---|---|
| q1_s01 | base | 16.915 | = | · | yes |
| q1_s01 | prenestoff | 10.947 | = | · | yes |
| q1_s01 | prenest | 11.077 | = | · | yes |
| q1_s01 | flat | 11.862 | 11.757 (0.99) | · | yes |
| q1_s01 | pureflat | 10.601 | 10.568 (1.00) | · | yes |
| q1_s50 | base | 18.671 | = | · | yes |
| q1_s50 | prenestoff | 12.835 | = | · | yes |
| q1_s50 | prenest | 12.861 | = | · | yes |
| q1_s50 | flat | 20.837 | 20.377 (0.98) | · | yes |
| q1_s50 | pureflat | 20.120 | 20.006 (0.99) | · | yes |
| q6_group | base | 22.468 | = | · | yes |
| q6_group | prenestoff | 16.528 | = | · | yes |
| q6_group | prenest | 12.710 | = | · | yes |
| q6_group | flat | 25.165 | 25.815 (1.03) | · | yes |
| q6_group | pureflat | 25.198 | 26.435 (1.05) | · | yes |
| q7_csa | base | 11.171 | = | 11.146 (1.00) | yes |
| q7_csa | prenestoff | 6.663 | = | 6.673 (1.00) | yes |
| q7_csa | prenest | 6.577 | = | 6.626 (1.01) | yes |
| q7_csa | flat | 10.995 | 28.350 (2.58) | 32.040 (2.91) | yes |
| q7_csa | pureflat | 7.371 | 9.196 (1.25) | 9.296 (1.26) | yes |
| q7_plots | base | 39.655 | = | 22.522 (0.57) | yes |
| q7_plots | prenestoff | 33.734 | = | 16.365 (0.49) | yes |
| q7_plots | prenest | 33.692 | = | 16.251 (0.48) | yes |
| q7_plots | flat | 91.524 | 76.282 (0.83) | 35.830 (0.39) | yes |
| q7_plots | pureflat | 93.425 | 77.933 (0.83) | 36.492 (0.39) | yes |

## 2-2 예상 행 수 vs 실제 행 수

전체 기록은 `cardinality.csv`(join, UNNEST, 그 입력 스캔마다 한 행: est, actual, q_error, 종류, 동적 필터 여부, flat 노드의 num_values).

| 데이터 | 쿼리 수 | join·UNNEST 행 | 스캔 행 | 오류 |
|---|---|---|---|---|
| trade | 40 | 154 | 169 | 0 |
| tpch_sf1 | 6 | 79 | 29 | 0 |
| tpch_sf10 | 5 | 34 | 22 | 0 |
| xmark | 4 | 40 | 46 | 0 |
| dblp | 4 | 16 | 20 | 0 |
| selectivity_random | 7 | 28 | 35 | 0 |
| selectivity_sorted | 7 | 28 | 35 | 0 |

## 2-3 요약

q-error = max(예상/실제, 실제/예상). 과소추정 = 예상 < 실제인 비율.
방식 A = base / prenestoff / prenest(builtin), 방식 B = flat / pure flat. A의 '중첩: UNNEST'가 B의 '중첩: parent-child' join에 해당합니다.
UNNEST는 자기 예상이 없어 입력의 예상을 그대로 씁니다(`src/planner/logical_operator.cpp:261-272`, 리스트 길이 1로 보는 셈).

### join·UNNEST의 q-error: trade (40개 쿼리)

| 방식 | 구성 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|---|
| A | base | nesting: UNNEST | 41 | 3.50 | 6.67 | 1219.5 | 95% |
| A | base | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | base | regular | 2 | 10256.71 | 18451.34 | 20500.0 | 100% |
| A | prenestoff | nesting: UNNEST | 41 | 3.50 | 6.67 | 1219.5 | 95% |
| A | prenestoff | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | prenestoff | regular | 2 | 10256.71 | 18451.34 | 20500.0 | 100% |
| A | prenest | nesting: UNNEST | 41 | 3.34 | 15.75 | 1250.0 | 76% |
| A | prenest | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | prenest | regular | 2 | 10256.71 | 18451.34 | 20500.0 | 100% |
| B | flat | nesting: parent-child | 8 | 4.17 | 1294.00 | 4267.1 | 62% |
| B | flat | nesting: sibling | 1 | 1.01 | 1.01 | 1.0 | 100% |
| B | flat | regular | 2 | 1787.63 | 3214.67 | 3571.4 | 50% |
| B | pureflat | nesting: parent-child | 8 | 3.17 | 1906.18 | 6307.7 | 62% |
| B | pureflat | nesting: sibling | 1 | 1.01 | 1.01 | 1.0 | 100% |
| B | pureflat | regular | 2 | 3501.92 | 6300.38 | 7000.0 | 100% |

방식별로 묶은 것 (구성 구분 없음):

| 방식 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|
| A | nesting | 126 | 3.50 | 8.75 | 1250.0 | 89% |
| A | regular | 6 | 10256.71 | 20500.00 | 20500.0 | 100% |
| B | nesting | 18 | 3.17 | 1294.00 | 6307.7 | 67% |
| B | regular | 4 | 1787.63 | 5971.43 | 7000.0 | 75% |

### join·UNNEST의 q-error: 지난 데이터 (TPC-H, XMark, DBLP, selectivity)

| 방식 | 구성 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|---|
| A | base | nesting: UNNEST | 56 | 1405.00 | 301979.50 | 1200243.0 | 88% |
| A | prenestoff | nesting: UNNEST | 56 | 1405.00 | 301979.50 | 1200243.0 | 88% |
| A | prenest | nesting: UNNEST | 56 | 1405.00 | 300000.00 | 1183318.2 | 82% |
| B | flat | nesting: parent-child | 40 | 2.75 | 40427.86 | 1000000.0 | 12% |
| B | flat | nesting: parent-child/same node | 2 | 1058422.54 | 1864839.71 | 2066444.0 | 0% |
| B | flat | regular | 15 | 2.10 | 484.15 | 23850.0 | 27% |

방식별로 묶은 것 (구성 구분 없음):

| 방식 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|
| A | nesting | 168 | 1405.00 | 300000.00 | 1200243.0 | 86% |
| B | nesting | 42 | 3.87 | 49423.37 | 2066444.0 | 12% |
| B | regular | 15 | 2.10 | 484.15 | 23850.0 | 27% |

### join·UNNEST의 q-error: 전체

| 방식 | 구성 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|---|
| A | base | nesting: UNNEST | 97 | 6.67 | 300000.00 | 1200243.0 | 91% |
| A | base | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | base | regular | 2 | 10256.71 | 18451.34 | 20500.0 | 100% |
| A | prenestoff | nesting: UNNEST | 97 | 6.67 | 300000.00 | 1200243.0 | 91% |
| A | prenestoff | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | prenestoff | regular | 2 | 10256.71 | 18451.34 | 20500.0 | 100% |
| A | prenest | nesting: UNNEST | 97 | 5.67 | 120000.00 | 1183318.2 | 79% |
| A | prenest | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | prenest | regular | 2 | 10256.71 | 18451.34 | 20500.0 | 100% |
| B | flat | nesting: parent-child | 48 | 3.48 | 26121.82 | 1000000.0 | 21% |
| B | flat | nesting: parent-child/same node | 2 | 1058422.54 | 1864839.71 | 2066444.0 | 0% |
| B | flat | nesting: sibling | 1 | 1.01 | 1.01 | 1.0 | 100% |
| B | flat | regular | 17 | 3.41 | 1777.60 | 23850.0 | 29% |
| B | pureflat | nesting: parent-child | 8 | 3.17 | 1906.18 | 6307.7 | 62% |
| B | pureflat | nesting: sibling | 1 | 1.01 | 1.01 | 1.0 | 100% |
| B | pureflat | regular | 2 | 3501.92 | 6300.38 | 7000.0 | 100% |

방식별로 묶은 것 (구성 구분 없음):

| 방식 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|
| A | nesting | 294 | 6.67 | 229691.00 | 1200243.0 | 87% |
| A | regular | 6 | 10256.71 | 20500.00 | 20500.0 | 100% |
| B | nesting | 60 | 3.48 | 40427.86 | 2066444.0 | 28% |
| B | regular | 19 | 3.83 | 4257.14 | 23850.0 | 37% |

### 입력 스캔의 q-error

스캔의 실제 행은 필터 뒤, 그리고 동적 join 필터 뒤의 값입니다. 동적 필터가 있는 스캔은 예상이 그것을 모르므로 따로 셉니다.

| 방식 | 구성 | 스캔 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|---|
| A | base | 동적 필터 | 3 | 1.00 | 2857.34 | 3571.4 | 0% |
| A | base | 필터 | 19 | 20.00 | 81472.15 | 200000.0 | 42% |
| A | base | 필터 없음 | 54 | 1.00 | 1.00 | 1.0 | 0% |
| A | prenestoff | 동적 필터 | 3 | 1.00 | 2857.34 | 3571.4 | 0% |
| A | prenestoff | 필터 | 19 | 20.00 | 81472.15 | 200000.0 | 42% |
| A | prenestoff | 필터 없음 | 54 | 1.00 | 1.00 | 1.0 | 0% |
| A | prenest | 동적 필터 | 3 | 1.00 | 2857.34 | 3571.4 | 0% |
| A | prenest | 필터 | 19 | 20.00 | 81472.15 | 200000.0 | 42% |
| A | prenest | 필터 없음 | 54 | 1.00 | 1.00 | 1.0 | 0% |
| B | flat | 동적 필터 | 47 | 1.01 | 2.68 | 121872.0 | 11% |
| B | flat | 필터 | 22 | 5.20 | 18200.00 | 200000.0 | 32% |
| B | flat | 필터 없음 | 39 | 1.00 | 1.00 | 58.6 | 0% |
| B | pureflat | 동적 필터 | 11 | 1.02 | 269.99 | 3571.4 | 0% |
| B | pureflat | 필터 | 5 | 2.50 | 13.80 | 20.0 | 60% |
| B | pureflat | 필터 없음 | 4 | 1.00 | 1.00 | 1.0 | 0% |

### flat 자식 노드 스캔의 예상 vs parquet num_values

`read_parquet_node`의 예상 = 노드 첫 leaf의 row group별 `num_values` 합(`extension/parquet/parquet_node_scan.cpp:186-191`).
num_values는 빈 리스트·NULL 리스트의 자리(placeholder)도 세므로, 그런 것이 있으면 실제 원소 수보다 큽니다.

| 관계 | 스캔 수 |
|---|---|
| est = nv_first | 42 |
| est = nv_first x f (필터) | 17 |

노드마다: num_values(첫 leaf)와 노드의 실제 행 수(빈·NULL 리스트 자리를 뺀 `read_parquet_node` 행 수)

| 데이터 | 파일 | 노드 | num_values (첫 leaf / 노드의 leaf들) | 노드 행 | num_values / 노드 행 | 쿼리에서 본 관계 |
|---|---|---|---|---|---|---|
| trade | trade_B.parquet | legs | 349,900,000 / 349900000 | 349,900,000 | 1.0000 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf1 | nestedregion.parquet | r_nations.n_customers.c_orders.o_lineitems | 6,051,219 / 6051219 | 6,001,215 | 1.0083 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf1 | nestedregion.parquet | r_nations.n_customers.c_orders | 1,550,004 / 1550004 | 1,500,000 | 1.0333 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf1 | nestedregion.parquet | r_nations.n_customers | 150,000 / 150000 | 150,000 | 1.0000 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf1 | nestedregion.parquet | r_nations | 25 / 25 | 25 | 1.0000 | est = nv_first |
| tpch_sf10 | nestedcustomer.parquet | c_orders.o_lineitems | 60,486,070 / 60486070 | 59,986,052 | 1.0083 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf10 | nestedcustomer.parquet | c_orders | 15,500,018 / 15500018 | 15,000,000 | 1.0333 | est = nv_first, est = nv_first x 0.2 |
| xmark | sf10.parquet | open_auctions.open_auction.bidder | 609,363 / 609363 | 597,777 | 1.0194 | est = nv_first, est = nv_first x 0.2 |
| xmark | sf10.parquet | open_auctions.open_auction | 120,000 / 120000 | 120,000 | 1.0000 | est = nv_first, est = nv_first x 0.2 |

