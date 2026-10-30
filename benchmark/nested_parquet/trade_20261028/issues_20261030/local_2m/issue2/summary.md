# 이슈 2: join 예상 오류 (issue2_2m)

```
date:     2026-10-30T14:07:59+09:00
host:     ChoiLY, 20 hardware threads, 15 GiB memory
cpu:      Intel(R) Core(TM) i5-14500
uptime:    14:07:59 up 3 days,  1:14,  1 user,  load average: 0.45, 0.33, 0.32
base:     v2.1.0-dev88383 a809d3cd51  /home/layun03/nested-bench/duckdb_base/build/release/duckdb
prenest:  v2.1.0-dev88385 fabde05fe6  /home/layun03/nested-bench/duckdb_prenest_base/build/release/duckdb
final:    v2.1.0-dev88419 2d345279c3  /home/layun03/nested-bench/duckdb_rey/build/release/duckdb
scripts:  69bd3cab48b nested_parquet: trade recheck with the float tolerance passes on apache10
data:     <2백만 행 샘플>/full, earlier datasets <합성 TPC-H>
runs:     2 at 1 thread (variants), cardinality at 8 threads
```

## 2-1 실행 계획 변형 (1스레드, RUNS 중 최소, 초)

- fixed: `join_order`를 끄고 원소 → 부모 → 차원 표 순서로 씀(build 쪽은 build_side_probe_side가 정함). builtin·flat은 글이 같고 설정만 다름.
- preagg: 차원 표 join 앞에서 집계(q7_csa: c0, c1별 / q7_plots: c8별). q1, q6은 차원 표 join이 없어 해당 없음.
- 괄호: 원래 대비 배수(< 1이면 빠름). '=': 원래와 같은 실행 계획이라 다시 재지 않음. 결과: 모든 변형이 원래 쿼리(base builtin)와 같으면 yes.
- 계획: `variant_plans/<쿼리>.<변형>.<구성>.txt`

| 쿼리 | 구성 | orig | fixed | preagg | 결과 |
|---|---|---|---|---|---|
| q1_s01 | base | 0.168 | = | · | yes |
| q1_s01 | prenestoff | 0.117 | = | · | yes |
| q1_s01 | prenest | 0.116 | = | · | yes |
| q1_s01 | flat | 0.090 | 0.090 (1.00) | · | yes |
| q1_s01 | pureflat | 0.095 | 0.092 (0.97) | · | yes |
| q1_s50 | base | 0.181 | = | · | yes |
| q1_s50 | prenestoff | 0.133 | = | · | yes |
| q1_s50 | prenest | 0.131 | = | · | yes |
| q1_s50 | flat | 0.169 | 0.176 (1.04) | · | yes |
| q1_s50 | pureflat | 0.190 | 0.196 (1.03) | · | yes |
| q6_group | base | 0.222 | = | · | yes |
| q6_group | prenestoff | 0.169 | = | · | yes |
| q6_group | prenest | 0.139 | = | · | yes |
| q6_group | flat | 0.230 | 0.249 (1.08) | · | yes |
| q6_group | pureflat | 0.250 | 0.272 (1.09) | · | yes |
| q7_csa | base | 0.110 | = | 0.111 (1.01) | yes |
| q7_csa | prenestoff | 0.071 | = | 0.072 (1.01) | yes |
| q7_csa | prenest | 0.073 | = | 0.070 (0.96) | yes |
| q7_csa | flat | 0.078 | 0.272 (3.49) | 0.293 (3.76) | yes |
| q7_csa | pureflat | 0.075 | 0.081 (1.08) | 0.081 (1.08) | yes |
| q7_plots | base | 0.386 | = | 0.225 (0.58) | yes |
| q7_plots | prenestoff | 0.351 | = | 0.173 (0.49) | yes |
| q7_plots | prenest | 0.331 | = | 0.169 (0.51) | yes |
| q7_plots | flat | 0.915 | 0.762 (0.83) | 0.346 (0.38) | yes |
| q7_plots | pureflat | 0.908 | 0.806 (0.89) | 0.385 (0.42) | yes |

## 2-2 예상 행 수 vs 실제 행 수

전체 기록은 `cardinality.csv`(join, UNNEST, 그 입력 스캔마다 한 행: est, actual, q_error, 종류, 동적 필터 여부, flat 노드의 num_values).

| 데이터 | 쿼리 수 | join·UNNEST 행 | 스캔 행 | 오류 |
|---|---|---|---|---|
| trade | 40 | 154 | 169 | 0 |
| tpch_sf1 | 6 | 79 | 29 | 0 |
| tpch_sf10 | 5 | 34 | 22 | 0 |

## 2-3 요약

q-error = max(예상/실제, 실제/예상). 과소추정 = 예상 < 실제인 비율.
방식 A = base / prenestoff / prenest(builtin), 방식 B = flat / pure flat. A의 '중첩: UNNEST'가 B의 '중첩: parent-child' join에 해당합니다.
UNNEST는 자기 예상이 없어 입력의 예상을 그대로 씁니다(`src/planner/logical_operator.cpp:261-272`, 리스트 길이 1로 보는 셈).

### join·UNNEST의 q-error: trade (40개 쿼리)

| 방식 | 구성 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|---|
| A | base | nesting: UNNEST | 41 | 3.50 | 6.67 | 1282.9 | 95% |
| A | base | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | base | regular | 2 | 201.58 | 352.12 | 389.8 | 100% |
| A | prenestoff | nesting: UNNEST | 41 | 3.50 | 6.67 | 1282.9 | 95% |
| A | prenestoff | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | prenestoff | regular | 2 | 201.58 | 352.12 | 389.8 | 100% |
| A | prenest | nesting: UNNEST | 41 | 3.34 | 15.76 | 1282.9 | 76% |
| A | prenest | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | prenest | regular | 2 | 201.58 | 352.12 | 389.8 | 100% |
| B | flat | nesting: parent-child | 8 | 4.17 | 1360.51 | 4488.8 | 62% |
| B | flat | nesting: sibling | 1 | 1.01 | 1.01 | 1.0 | 100% |
| B | flat | regular | 2 | 1878.09 | 3377.49 | 3752.3 | 50% |
| B | pureflat | nesting: parent-child | 8 | 3.17 | 49.85 | 119.9 | 62% |
| B | pureflat | nesting: sibling | 1 | 1.01 | 1.01 | 1.0 | 100% |
| B | pureflat | regular | 2 | 68.54 | 120.31 | 133.2 | 100% |

방식별로 묶은 것 (구성 구분 없음):

| 방식 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|
| A | nesting | 126 | 3.50 | 8.76 | 1282.9 | 89% |
| A | regular | 6 | 201.58 | 389.75 | 389.8 | 100% |
| B | nesting | 18 | 3.17 | 49.85 | 4488.8 | 67% |
| B | regular | 4 | 68.54 | 2666.62 | 3752.3 | 75% |

### join·UNNEST의 q-error: 지난 데이터 (TPC-H, XMark, DBLP, selectivity)

| 방식 | 구성 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|---|
| A | base | nesting: UNNEST | 34 | 3000.00 | 33274.80 | 80000.0 | 100% |
| A | prenestoff | nesting: UNNEST | 34 | 3000.00 | 33274.80 | 80000.0 | 100% |
| A | prenest | nesting: UNNEST | 34 | 679.60 | 20000.00 | 78018.2 | 88% |
| B | flat | nesting: parent-child | 11 | 3.16 | 16200.00 | 16200.0 | 36% |

방식별로 묶은 것 (구성 구분 없음):

| 방식 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|
| A | nesting | 102 | 1103.30 | 20000.00 | 80000.0 | 96% |
| B | nesting | 11 | 3.16 | 16200.00 | 16200.0 | 36% |

### join·UNNEST의 q-error: 전체

| 방식 | 구성 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|---|
| A | base | nesting: UNNEST | 75 | 5.00 | 20000.00 | 80000.0 | 97% |
| A | base | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | base | regular | 2 | 201.58 | 352.12 | 389.8 | 100% |
| A | prenestoff | nesting: UNNEST | 75 | 5.00 | 20000.00 | 80000.0 | 97% |
| A | prenestoff | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | prenestoff | regular | 2 | 201.58 | 352.12 | 389.8 | 100% |
| A | prenest | nesting: UNNEST | 75 | 5.00 | 15100.20 | 78018.2 | 81% |
| A | prenest | nesting: sibling | 1 | 16.78 | 16.78 | 16.8 | 100% |
| A | prenest | regular | 2 | 201.58 | 352.12 | 389.8 | 100% |
| B | flat | nesting: parent-child | 19 | 3.16 | 6831.02 | 16200.0 | 47% |
| B | flat | nesting: sibling | 1 | 1.01 | 1.01 | 1.0 | 100% |
| B | flat | regular | 2 | 1878.09 | 3377.49 | 3752.3 | 50% |
| B | pureflat | nesting: parent-child | 8 | 3.17 | 49.85 | 119.9 | 62% |
| B | pureflat | nesting: sibling | 1 | 1.01 | 1.01 | 1.0 | 100% |
| B | pureflat | regular | 2 | 68.54 | 120.31 | 133.2 | 100% |

방식별로 묶은 것 (구성 구분 없음):

| 방식 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|
| A | nesting | 228 | 5.00 | 19909.00 | 80000.0 | 92% |
| A | regular | 6 | 201.58 | 389.75 | 389.8 | 100% |
| B | nesting | 29 | 3.16 | 993.69 | 16200.0 | 55% |
| B | regular | 4 | 68.54 | 2666.62 | 3752.3 | 75% |

### 입력 스캔의 q-error

스캔의 실제 행은 필터 뒤, 그리고 동적 join 필터 뒤의 값입니다. 동적 필터가 있는 스캔은 예상이 그것을 모르므로 따로 셉니다.

| 방식 | 구성 | 스캔 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |
|---|---|---|---|---|---|---|---|
| A | base | 동적 필터 | 3 | 1.00 | 3002.08 | 3752.3 | 0% |
| A | base | 필터 | 5 | 2.50 | 13.80 | 20.0 | 40% |
| A | base | 필터 없음 | 46 | 1.00 | 1.00 | 1.0 | 0% |
| A | prenestoff | 동적 필터 | 3 | 1.00 | 3002.08 | 3752.3 | 0% |
| A | prenestoff | 필터 | 5 | 2.50 | 13.80 | 20.0 | 40% |
| A | prenestoff | 필터 없음 | 46 | 1.00 | 1.00 | 1.0 | 0% |
| A | prenest | 동적 필터 | 3 | 1.00 | 3002.08 | 3752.3 | 0% |
| A | prenest | 필터 | 5 | 2.50 | 13.80 | 20.0 | 40% |
| A | prenest | 필터 없음 | 46 | 1.00 | 1.00 | 1.0 | 0% |
| B | flat | 동적 필터 | 19 | 1.00 | 2.38 | 2.6 | 26% |
| B | flat | 필터 | 13 | 3.13 | 5.50 | 20.0 | 31% |
| B | flat | 필터 없음 | 6 | 1.00 | 33.65 | 53.8 | 0% |
| B | pureflat | 동적 필터 | 11 | 1.05 | 3752.34 | 4488.8 | 0% |
| B | pureflat | 필터 | 5 | 2.50 | 13.80 | 20.0 | 60% |
| B | pureflat | 필터 없음 | 4 | 1.00 | 1.00 | 1.0 | 0% |

### flat 자식 노드 스캔의 예상 vs parquet num_values

`read_parquet_node`의 예상 = 노드 첫 leaf의 row group별 `num_values` 합(`extension/parquet/parquet_node_scan.cpp:186-191`).
num_values는 빈 리스트·NULL 리스트의 자리(placeholder)도 세므로, 그런 것이 있으면 실제 원소 수보다 큽니다.

| 관계 | 스캔 수 |
|---|---|
| est = nv_first | 13 |
| est = nv_first x f (필터) | 12 |

노드마다: num_values(첫 leaf)와 노드의 실제 행 수(빈·NULL 리스트 자리를 뺀 `read_parquet_node` 행 수)

| 데이터 | 파일 | 노드 | num_values (첫 leaf / 노드의 leaf들) | 노드 행 | num_values / 노드 행 | 쿼리에서 본 관계 |
|---|---|---|---|---|---|---|
| trade | trade_B.parquet | legs | 6,997,998 / 6997998 | 6,997,998 | 1.0000 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf1 | nestedregion.parquet | r_nations.n_customers.c_orders.o_lineitems | 405,000 / 405000 | 400,000 | 1.0125 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf1 | nestedregion.parquet | r_nations.n_customers.c_orders | 105,000 / 105000 | 100,000 | 1.0500 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf1 | nestedregion.parquet | r_nations.n_customers | 15,000 / 15000 | 15,000 | 1.0000 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf1 | nestedregion.parquet | r_nations | 25 / 25 | 25 | 1.0000 | est = nv_first |
| tpch_sf10 | nestedcustomer.parquet | c_orders.o_lineitems | 405,000 / 405000 | 400,000 | 1.0125 | est = nv_first, est = nv_first x 0.2 |
| tpch_sf10 | nestedcustomer.parquet | c_orders | 105,000 / 105000 | 100,000 | 1.0500 | est = nv_first, est = nv_first x 0.2 |

