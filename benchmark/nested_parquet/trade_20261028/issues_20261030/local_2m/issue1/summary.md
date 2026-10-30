# 이슈 1: Unnest 오버헤드 분해 (issue1)

```
date:     2026-10-30T14:26:59+09:00
host:     ChoiLY, 20 hardware threads, 15 GiB memory
cpu:      Intel(R) Core(TM) i5-14500
uptime:    14:26:59 up 3 days,  1:33,  1 user,  load average: 0.03, 0.12, 0.29
base:     v2.1.0-dev88383 a809d3cd51  /home/layun03/nested-bench/duckdb_base/build/release/duckdb
prenest:  v2.1.0-dev88385 fabde05fe6  /home/layun03/nested-bench/duckdb_prenest_base/build/release/duckdb
final:    v2.1.0-dev88419 2d345279c3  /home/layun03/nested-bench/duckdb_rey/build/release/duckdb
perf:     perf version 6.8.12  (perf)
scripts:  2424b48e6a5 nested_parquet: trade handoff, the source of prenestoff's string copies and the issues of 2026-10-30
data:     <2백만 행 샘플>/full
runs:     3, perf 1000 Hz
```

## 1-1 단계 누적 쿼리 (legs, 1스레드)

단계: s1 상자(목록만) → s2 펼치기(count) → s2f 펼치기 + s3에서 쓰는 필드 2개 → s3 q2_c50 조건과 합계.
flat·pure flat에는 상자가 없어 s1은 키만 읽고, s2와 s2f는 같은 쿼리입니다. 쿼리는 `queries_stage/`, 계획 확인은 `stage_check.md`.

### 시간 (초, RUNS 중 최소) / 결과 일치

| 구성 | s1_box | s2_unnest | s2f_fields | s3_cond |
|---|---|---|---|---|
| base | 0.149 (yes) | 0.179 (yes) | 0.182 (yes) | 0.272 (yes) |
| prenestoff | 0.150 (yes) | 0.181 (yes) | 0.144 (yes) | 0.235 (yes) |
| prenest | 0.151 (yes) | 0.179 (yes) | 0.145 (yes) | 0.180 (yes) |
| flat | 0.045 (yes) | 0.064 (yes) | 0.064 (yes) | 0.123 (yes) |
| pureflat | 0.031 (yes) | 0.039 (yes) | 0.040 (yes) | 0.048 (yes) |

### perf 범주 (CPU 초), 새 기준(call stack)

| 구성 | 단계 | wall | CPU | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base | s1_box | 0.16 | 0.15 | 0.06 | 0.10 | · | · | · | · | · | · |
| base | s2_unnest | 0.19 | 0.19 | 0.05 | 0.11 | 0.03 | · | · | · | · | · |
| base | s2f_fields | 0.19 | 0.19 | 0.06 | 0.09 | 0.03 | 0.01 | · | · | · | · |
| base | s3_cond | 0.28 | 0.27 | 0.06 | 0.09 | 0.05 | 0.08 | · | · | · | · |
| prenestoff | s1_box | 0.16 | 0.15 | 0.05 | 0.11 | · | · | · | · | · | · |
| prenestoff | s2_unnest | 0.19 | 0.18 | 0.05 | 0.09 | 0.03 | · | · | · | · | · |
| prenestoff | s2f_fields | 0.15 | 0.15 | 0.03 | 0.08 | 0.04 | · | · | · | · | · |
| prenestoff | s3_cond | 0.23 | 0.23 | 0.02 | 0.09 | 0.04 | 0.07 | · | · | · | 0.01 |
| prenest | s1_box | 0.17 | 0.16 | 0.05 | 0.11 | · | · | · | · | · | · |
| prenest | s2_unnest | 0.20 | 0.19 | 0.06 | 0.09 | 0.04 | · | · | · | · | · |
| prenest | s2f_fields | 0.15 | 0.15 | 0.03 | 0.08 | 0.02 | · | · | · | · | · |
| prenest | s3_cond | 0.18 | 0.17 | 0.02 | 0.08 | 0.03 | 0.04 | · | · | · | · |
| flat | s1_box | 0.05 | 0.05 | 0.02 | · | · | · | 0.03 | · | · | · |
| flat | s2_unnest | 0.07 | 0.07 | 0.03 | · | · | · | 0.03 | · | 0.01 | · |
| flat | s2f_fields | 0.07 | 0.07 | 0.03 | · | · | · | 0.03 | · | 0.01 | · |
| flat | s3_cond | 0.12 | 0.12 | 0.04 | · | · | 0.04 | 0.04 | · | · | · |
| pureflat | s1_box | 0.03 | 0.03 | 0.02 | · | · | · | · | · | · | · |
| pureflat | s2_unnest | 0.04 | 0.03 | 0.03 | · | · | · | · | · | 0.01 | · |
| pureflat | s2f_fields | 0.04 | 0.03 | 0.03 | · | · | · | · | · | · | · |
| pureflat | s3_cond | 0.06 | 0.04 | 0.04 | · | · | · | · | · | 0.01 | · |

### perf 범주 (CPU 초), 옛 기준(잎 함수 이름)

| 구성 | 단계 | wall | CPU | 디코드 | 조립 | 키 | FILTER | UNNEST | join | 집계 | 식·벡터 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | s1_box | 0.16 | 0.15 | 0.04 | 0.02 | · | · | · | · | · | 0.05 | 0.04 |
| base | s2_unnest | 0.19 | 0.19 | 0.03 | 0.02 | · | · | 0.03 | · | · | 0.08 | 0.04 |
| base | s2f_fields | 0.19 | 0.19 | 0.04 | 0.01 | · | · | 0.02 | · | · | 0.06 | 0.05 |
| base | s3_cond | 0.28 | 0.27 | 0.03 | 0.01 | · | · | 0.04 | · | · | 0.11 | 0.07 |
| prenestoff | s1_box | 0.16 | 0.15 | 0.03 | 0.02 | · | · | · | · | · | 0.07 | 0.04 |
| prenestoff | s2_unnest | 0.19 | 0.18 | 0.03 | 0.02 | · | · | 0.03 | · | · | 0.06 | 0.05 |
| prenestoff | s2f_fields | 0.15 | 0.15 | 0.01 | 0.02 | · | · | 0.03 | · | · | 0.06 | 0.03 |
| prenestoff | s3_cond | 0.23 | 0.23 | 0.01 | 0.02 | · | · | 0.03 | · | · | 0.09 | 0.06 |
| prenest | s1_box | 0.17 | 0.16 | 0.03 | 0.01 | · | · | · | · | · | 0.08 | 0.04 |
| prenest | s2_unnest | 0.20 | 0.19 | 0.04 | 0.02 | · | · | 0.04 | · | · | 0.06 | 0.04 |
| prenest | s2f_fields | 0.15 | 0.15 | 0.02 | 0.02 | · | · | 0.02 | · | · | 0.05 | 0.03 |
| prenest | s3_cond | 0.18 | 0.17 | 0.01 | 0.04 | · | · | 0.03 | · | · | 0.06 | 0.03 |
| flat | s1_box | 0.05 | 0.05 | 0.01 | · | 0.03 | · | · | · | · | · | 0.01 |
| flat | s2_unnest | 0.07 | 0.07 | 0.02 | · | 0.03 | · | · | · | 0.01 | 0.01 | 0.01 |
| flat | s2f_fields | 0.07 | 0.07 | 0.02 | · | 0.03 | · | · | · | 0.01 | · | 0.01 |
| flat | s3_cond | 0.12 | 0.12 | 0.02 | · | 0.04 | 0.01 | · | · | · | 0.02 | 0.03 |
| pureflat | s1_box | 0.03 | 0.03 | 0.02 | · | · | · | · | · | · | · | 0.01 |
| pureflat | s2_unnest | 0.04 | 0.03 | 0.01 | · | · | · | · | · | · | 0.01 | 0.01 |
| pureflat | s2f_fields | 0.04 | 0.03 | 0.02 | · | · | · | · | · | · | · | 0.01 |
| pureflat | s3_cond | 0.06 | 0.04 | 0.02 | · | · | · | · | · | · | 0.01 | 0.01 |

### 단계 사이의 차이: 측정 시간 차이 vs perf 범주 차이 (초), 새 기준(call stack)

Δwall은 stage_time.csv(최소 시간)의 차이, 나머지는 perf 실행 한 번의 범주별 CPU 차이입니다.
기대: s1→s2는 UNNEST, s2→s2f는 (가지치기하는 구성에서) 디코드·조립 감소 + 필드 꺼내기, s2f→s3는 원소 다루기(조건)와 집계.

| 구성 | 단계 | Δwall | ΔCPU(perf) | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base | s1→s2 | 0.03 | 0.04 | · | 0.01 | 0.03 | · | · | · | · | · |
| base | s2→s2f | · | -0.01 | 0.01 | -0.01 | · | 0.01 | · | · | · | · |
| base | s2f→s3 | 0.09 | 0.08 | · | -0.01 | 0.02 | 0.08 | · | · | · | · |
| prenestoff | s1→s2 | 0.03 | 0.03 | 0.01 | -0.01 | 0.03 | · | · | · | · | · |
| prenestoff | s2→s2f | -0.04 | -0.04 | -0.03 | -0.01 | · | · | · | · | · | · |
| prenestoff | s2f→s3 | 0.09 | 0.08 | -0.01 | 0.01 | · | 0.07 | · | · | · | 0.01 |
| prenest | s1→s2 | 0.03 | 0.02 | · | -0.02 | 0.04 | · | · | · | · | · |
| prenest | s2→s2f | -0.03 | -0.04 | -0.02 | -0.01 | -0.02 | · | · | · | · | · |
| prenest | s2f→s3 | 0.04 | 0.02 | -0.01 | -0.01 | 0.01 | 0.03 | · | · | · | · |
| flat | s1→s2 | 0.02 | 0.02 | 0.01 | · | · | · | · | · | 0.01 | · |
| flat | s2→s2f | · | · | · | · | · | · | · | · | · | · |
| flat | s2f→s3 | 0.06 | 0.06 | 0.01 | · | · | 0.04 | 0.01 | · | -0.01 | · |
| pureflat | s1→s2 | 0.01 | 0.01 | · | · | · | · | · | · | · | · |
| pureflat | s2→s2f | · | · | · | · | · | · | · | · | · | · |
| pureflat | s2f→s3 | 0.01 | 0.01 | 0.01 | · | · | · | · | · | · | · |

### 단계 사이의 차이: 측정 시간 차이 vs perf 범주 차이 (초), 옛 기준(잎 함수 이름)

| 구성 | 단계 | Δwall | ΔCPU(perf) | 디코드 | 조립 | 키 | FILTER | UNNEST | join | 집계 | 식·벡터 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | s1→s2 | 0.03 | 0.04 | -0.01 | -0.01 | · | · | 0.03 | · | · | 0.02 | · |
| base | s2→s2f | · | -0.01 | 0.01 | · | · | · | -0.01 | · | · | -0.01 | 0.01 |
| base | s2f→s3 | 0.09 | 0.08 | -0.01 | · | · | · | 0.02 | · | · | 0.05 | 0.03 |
| prenestoff | s1→s2 | 0.03 | 0.03 | · | · | · | · | 0.03 | · | · | -0.01 | 0.01 |
| prenestoff | s2→s2f | -0.04 | -0.04 | -0.02 | · | · | · | · | · | · | · | -0.02 |
| prenestoff | s2f→s3 | 0.09 | 0.08 | · | · | · | · | · | · | · | 0.04 | 0.04 |
| prenest | s1→s2 | 0.03 | 0.02 | · | · | · | · | 0.04 | · | · | -0.02 | · |
| prenest | s2→s2f | -0.03 | -0.04 | -0.01 | 0.01 | · | · | -0.02 | · | · | -0.01 | · |
| prenest | s2f→s3 | 0.04 | 0.02 | -0.01 | 0.02 | · | · | 0.01 | · | · | · | · |
| flat | s1→s2 | 0.02 | 0.02 | 0.01 | · | · | · | · | · | 0.01 | · | · |
| flat | s2→s2f | · | · | · | · | · | · | · | · | · | · | · |
| flat | s2f→s3 | 0.06 | 0.06 | · | · | 0.01 | 0.01 | · | · | -0.01 | 0.02 | 0.03 |
| pureflat | s1→s2 | 0.01 | 0.01 | -0.01 | · | · | · | · | · | · | · | 0.01 |
| pureflat | s2→s2f | · | · | 0.01 | · | · | · | · | · | · | · | · |
| pureflat | s2f→s3 | 0.01 | 0.01 | · | · | · | · | · | · | · | 0.01 | · |

## 1-2 파라미터별 분해 (1스레드, perf)

### 리스트와 원소 수 (base EXPLAIN ANALYZE와 파일)

| 쿼리 | 열 | 리스트 (파일 행) | 원소 (파일) | 스캔이 낸 리스트 | UNNEST 원소 | 통과 원소 |
|---|---|---|---|---|---|---|
| q1_s01 | legs | 2,000,000 | 6,997,998 | 20,000 | 70,600 | 70,600 |
| q1_s50 | legs | 2,000,000 | 6,997,998 | 1,001,369 | 3,504,198 | 3,504,198 |
| q1_s90 | legs | 2,000,000 | 6,997,998 | 1,801,509 | 6,304,074 | 6,304,074 |
| q2_c01 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 65,358 |
| q2_c10 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 707,874 |
| q2_c25 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 1,758,205 |
| q2_c50 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 3,492,296 |
| q2_c75 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 5,273,310 |
| q2_s50 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 3,504,198 |
| q3_c11 | c11 | 2,000,000 | 13,345,090 | 2,000,000 | 13,345,090 | 6,683,642 |
| q3_c12 | c12 | 2,000,000 | 5,596,070 | 2,000,000 | 5,596,070 | 2,806,579 |
| q3_c13 | c13 | 2,000,000 | 3,847,601 | 2,000,000 | 3,847,601 | 2,066,564 |

### 범주별 CPU 초, 새 기준(call stack)

| 쿼리 | 구성 | wall | CPU | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| q1_s01 | base | 0.17 | 0.16 | 0.07 | 0.09 | · | · | · | · | · | · |
| q1_s01 | prenestoff | 0.12 | 0.11 | 0.03 | 0.08 | · | · | · | · | · | 0.01 |
| q1_s01 | prenest | 0.12 | 0.11 | 0.03 | 0.08 | · | · | · | · | · | 0.01 |
| q1_s01 | flat | 0.09 | 0.09 | 0.01 | · | · | · | 0.04 | 0.03 | · | 0.01 |
| q1_s01 | pureflat | 0.10 | 0.08 | 0.07 | · | · | · | · | 0.01 | · | · |
| q1_s50 | base | 0.19 | 0.18 | 0.05 | 0.10 | 0.02 | · | · | · | · | · |
| q1_s50 | prenestoff | 0.14 | 0.12 | 0.02 | 0.08 | 0.02 | · | · | · | · | · |
| q1_s50 | prenest | 0.14 | 0.13 | 0.02 | 0.08 | 0.02 | · | · | · | · | 0.01 |
| q1_s50 | flat | 0.17 | 0.17 | 0.03 | · | · | · | 0.03 | 0.10 | · | 0.01 |
| q1_s50 | pureflat | 0.19 | 0.17 | 0.07 | · | · | · | · | 0.09 | 0.01 | · |
| q1_s90 | base | 0.20 | 0.20 | 0.06 | 0.10 | 0.03 | · | · | · | · | · |
| q1_s90 | prenestoff | 0.15 | 0.15 | 0.02 | 0.09 | 0.03 | · | · | · | · | 0.01 |
| q1_s90 | prenest | 0.15 | 0.14 | 0.03 | 0.08 | 0.03 | · | · | · | · | 0.01 |
| q1_s90 | flat | 0.26 | 0.25 | 0.02 | · | · | · | 0.04 | 0.18 | 0.01 | 0.01 |
| q1_s90 | pureflat | 0.28 | 0.27 | 0.07 | · | · | · | · | 0.18 | 0.02 | 0.01 |
| q2_c01 | base | 0.23 | 0.23 | 0.05 | 0.10 | 0.02 | 0.05 | · | · | · | 0.01 |
| q2_c01 | prenestoff | 0.19 | 0.18 | 0.03 | 0.10 | 0.02 | 0.04 | · | · | · | · |
| q2_c01 | prenest | 0.08 | 0.07 | 0.03 | 0.03 | · | 0.01 | · | · | · | · |
| q2_c01 | flat | 0.10 | 0.10 | 0.03 | · | · | 0.03 | 0.04 | · | · | · |
| q2_c01 | pureflat | 0.04 | 0.04 | 0.03 | · | · | 0.01 | · | · | · | · |
| q2_c10 | base | 0.25 | 0.24 | 0.05 | 0.09 | 0.03 | 0.05 | · | · | · | 0.01 |
| q2_c10 | prenestoff | 0.20 | 0.20 | 0.04 | 0.07 | 0.04 | 0.05 | · | · | · | · |
| q2_c10 | prenest | 0.10 | 0.10 | 0.03 | 0.03 | 0.02 | 0.02 | · | · | · | · |
| q2_c10 | flat | 0.10 | 0.10 | 0.03 | · | · | 0.03 | 0.04 | · | · | · |
| q2_c10 | pureflat | 0.04 | 0.04 | 0.03 | · | · | 0.01 | · | · | · | · |
| q2_c25 | base | 0.25 | 0.24 | 0.07 | 0.10 | 0.03 | 0.05 | · | · | · | · |
| q2_c25 | prenestoff | 0.20 | 0.20 | 0.03 | 0.09 | 0.03 | 0.05 | · | · | · | 0.01 |
| q2_c25 | prenest | 0.14 | 0.13 | 0.03 | 0.04 | 0.03 | 0.03 | · | · | · | · |
| q2_c25 | flat | 0.10 | 0.10 | 0.03 | · | · | 0.03 | 0.03 | · | · | · |
| q2_c25 | pureflat | 0.05 | 0.04 | 0.04 | · | · | · | · | · | · | · |
| q2_c50 | base | 0.28 | 0.27 | 0.06 | 0.09 | 0.03 | 0.09 | · | · | · | 0.01 |
| q2_c50 | prenestoff | 0.24 | 0.23 | 0.03 | 0.09 | 0.02 | 0.08 | · | · | · | 0.01 |
| q2_c50 | prenest | 0.17 | 0.17 | 0.03 | 0.08 | 0.03 | 0.04 | · | · | · | 0.01 |
| q2_c50 | flat | 0.13 | 0.13 | 0.04 | · | · | 0.05 | 0.03 | · | · | · |
| q2_c50 | pureflat | 0.05 | 0.05 | 0.03 | · | · | 0.01 | · | · | 0.01 | · |
| q2_c75 | base | 0.26 | 0.26 | 0.06 | 0.12 | 0.02 | 0.05 | · | · | · | 0.01 |
| q2_c75 | prenestoff | 0.22 | 0.21 | 0.04 | 0.07 | 0.04 | 0.06 | · | · | 0.01 | 0.01 |
| q2_c75 | prenest | 0.20 | 0.20 | 0.03 | 0.09 | 0.03 | 0.05 | · | · | · | · |
| q2_c75 | flat | 0.12 | 0.12 | 0.03 | · | · | 0.06 | 0.03 | · | 0.01 | · |
| q2_c75 | pureflat | 0.05 | 0.04 | 0.04 | · | · | · | · | · | · | · |
| q2_s50 | base | 0.20 | 0.20 | 0.05 | 0.10 | 0.02 | 0.02 | · | · | · | 0.01 |
| q2_s50 | prenestoff | 0.16 | 0.15 | 0.01 | 0.09 | 0.03 | 0.01 | · | · | · | 0.01 |
| q2_s50 | prenest | 0.13 | 0.12 | 0.02 | 0.07 | 0.03 | 0.01 | · | · | · | · |
| q2_s50 | flat | 0.06 | 0.06 | 0.02 | · | · | · | 0.03 | · | · | · |
| q2_s50 | pureflat | 0.04 | 0.03 | 0.02 | · | · | 0.01 | · | · | 0.01 | · |
| q3_c11 | base | 0.14 | 0.13 | 0.04 | 0.03 | 0.04 | 0.02 | · | · | · | 0.01 |
| q3_c11 | prenestoff | 0.14 | 0.14 | 0.03 | 0.05 | 0.04 | 0.01 | · | · | · | 0.01 |
| q3_c11 | prenest | 0.14 | 0.14 | 0.04 | 0.05 | 0.04 | 0.01 | · | · | · | · |
| q3_c11 | flat | 0.12 | 0.11 | 0.05 | · | · | 0.01 | 0.04 | · | 0.01 | · |
| q3_c11 | pureflat | 0.07 | 0.06 | 0.04 | · | · | 0.01 | · | · | 0.01 | · |
| q3_c12 | base | 0.07 | 0.07 | 0.02 | 0.02 | 0.02 | · | · | · | · | · |
| q3_c12 | prenestoff | 0.07 | 0.07 | 0.02 | 0.02 | 0.03 | · | · | · | · | · |
| q3_c12 | prenest | 0.07 | 0.07 | 0.01 | 0.02 | 0.02 | 0.01 | · | · | · | · |
| q3_c12 | flat | 0.05 | 0.05 | 0.01 | · | · | 0.01 | 0.03 | · | · | · |
| q3_c12 | pureflat | 0.03 | 0.02 | 0.02 | · | · | 0.01 | · | · | · | · |
| q3_c13 | base | 0.06 | 0.06 | 0.01 | 0.02 | 0.02 | · | · | · | · | · |
| q3_c13 | prenestoff | 0.06 | 0.06 | 0.01 | 0.02 | 0.02 | · | · | · | · | · |
| q3_c13 | prenest | 0.06 | 0.06 | 0.01 | 0.02 | 0.02 | 0.01 | · | · | · | · |
| q3_c13 | flat | 0.04 | 0.04 | 0.01 | · | · | · | 0.03 | · | · | · |
| q3_c13 | pureflat | 0.02 | 0.01 | 0.01 | · | · | · | · | · | · | · |

### 범주별 CPU 초, 옛 기준(잎 함수 이름)

| 쿼리 | 구성 | wall | CPU | 디코드 | 조립 | 키 | FILTER | UNNEST | join | 집계 | 식·벡터 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1_s01 | base | 0.17 | 0.16 | 0.04 | 0.01 | · | · | · | · | · | 0.07 | 0.04 |
| q1_s01 | prenestoff | 0.12 | 0.11 | 0.02 | 0.02 | · | · | · | · | · | 0.05 | 0.03 |
| q1_s01 | prenest | 0.12 | 0.11 | 0.02 | 0.02 | · | · | · | · | · | 0.05 | 0.02 |
| q1_s01 | flat | 0.09 | 0.09 | 0.01 | · | 0.04 | · | · | 0.02 | · | 0.01 | 0.02 |
| q1_s01 | pureflat | 0.10 | 0.08 | 0.05 | · | · | · | · | · | · | 0.01 | 0.02 |
| q1_s50 | base | 0.19 | 0.18 | 0.03 | 0.02 | · | · | 0.02 | · | · | 0.07 | 0.05 |
| q1_s50 | prenestoff | 0.14 | 0.12 | 0.01 | 0.03 | · | · | 0.02 | · | · | 0.05 | 0.02 |
| q1_s50 | prenest | 0.14 | 0.13 | 0.01 | 0.02 | · | · | 0.02 | · | · | 0.05 | 0.02 |
| q1_s50 | flat | 0.17 | 0.17 | 0.02 | · | 0.03 | · | · | 0.06 | 0.02 | 0.02 | 0.03 |
| q1_s50 | pureflat | 0.19 | 0.17 | 0.05 | · | · | · | · | 0.06 | 0.02 | 0.02 | 0.03 |
| q1_s90 | base | 0.20 | 0.20 | 0.03 | 0.02 | · | · | 0.02 | · | · | 0.07 | 0.05 |
| q1_s90 | prenestoff | 0.15 | 0.15 | 0.01 | 0.02 | · | · | 0.02 | · | · | 0.06 | 0.04 |
| q1_s90 | prenest | 0.15 | 0.14 | 0.02 | 0.02 | · | · | 0.02 | · | · | 0.05 | 0.04 |
| q1_s90 | flat | 0.26 | 0.25 | 0.01 | · | 0.04 | · | · | 0.13 | 0.04 | 0.02 | 0.03 |
| q1_s90 | pureflat | 0.28 | 0.27 | 0.04 | · | · | · | · | 0.14 | 0.02 | 0.02 | 0.05 |
| q2_c01 | base | 0.23 | 0.23 | 0.03 | 0.02 | · | · | 0.02 | · | · | 0.09 | 0.06 |
| q2_c01 | prenestoff | 0.19 | 0.18 | 0.02 | 0.04 | · | · | 0.02 | · | · | 0.06 | 0.04 |
| q2_c01 | prenest | 0.08 | 0.07 | 0.02 | 0.02 | · | · | · | · | · | 0.01 | 0.02 |
| q2_c01 | flat | 0.10 | 0.10 | 0.01 | · | 0.04 | 0.01 | · | · | · | 0.02 | 0.03 |
| q2_c01 | pureflat | 0.04 | 0.04 | 0.02 | · | · | · | · | · | · | · | 0.01 |
| q2_c10 | base | 0.25 | 0.24 | 0.04 | 0.01 | · | · | 0.03 | · | · | 0.09 | 0.07 |
| q2_c10 | prenestoff | 0.20 | 0.20 | 0.02 | 0.02 | · | · | 0.04 | · | · | 0.08 | 0.04 |
| q2_c10 | prenest | 0.10 | 0.10 | 0.02 | 0.02 | · | · | 0.02 | · | · | 0.02 | 0.02 |
| q2_c10 | flat | 0.10 | 0.10 | 0.02 | · | 0.04 | 0.01 | · | · | · | 0.02 | 0.02 |
| q2_c10 | pureflat | 0.04 | 0.04 | 0.01 | · | · | · | · | · | · | 0.01 | 0.01 |
| q2_c25 | base | 0.25 | 0.24 | 0.04 | 0.02 | · | · | 0.02 | · | · | 0.10 | 0.05 |
| q2_c25 | prenestoff | 0.20 | 0.20 | 0.02 | 0.02 | · | · | 0.03 | · | · | 0.09 | 0.05 |
| q2_c25 | prenest | 0.14 | 0.13 | 0.01 | 0.03 | · | · | 0.03 | · | · | 0.03 | 0.03 |
| q2_c25 | flat | 0.10 | 0.10 | 0.02 | · | 0.03 | 0.01 | · | · | · | 0.01 | 0.02 |
| q2_c25 | pureflat | 0.05 | 0.04 | 0.02 | · | · | · | · | · | · | · | 0.02 |
| q2_c50 | base | 0.28 | 0.27 | 0.03 | 0.02 | · | · | 0.03 | · | · | 0.12 | 0.08 |
| q2_c50 | prenestoff | 0.24 | 0.23 | 0.01 | 0.02 | · | · | 0.02 | · | · | 0.11 | 0.06 |
| q2_c50 | prenest | 0.17 | 0.17 | 0.02 | 0.04 | · | · | 0.02 | · | · | 0.05 | 0.04 |
| q2_c50 | flat | 0.13 | 0.13 | 0.02 | · | 0.03 | 0.02 | · | · | · | 0.02 | 0.03 |
| q2_c50 | pureflat | 0.05 | 0.05 | 0.02 | · | · | · | · | · | 0.01 | 0.01 | 0.01 |
| q2_c75 | base | 0.26 | 0.26 | 0.04 | 0.02 | · | · | 0.02 | · | · | 0.11 | 0.06 |
| q2_c75 | prenestoff | 0.22 | 0.21 | 0.02 | 0.02 | · | · | 0.03 | · | · | 0.09 | 0.05 |
| q2_c75 | prenest | 0.20 | 0.20 | 0.02 | 0.03 | · | · | 0.03 | · | · | 0.07 | 0.06 |
| q2_c75 | flat | 0.12 | 0.12 | 0.02 | · | 0.03 | 0.02 | · | · | 0.01 | 0.03 | 0.02 |
| q2_c75 | pureflat | 0.05 | 0.04 | 0.02 | · | · | · | · | · | · | 0.01 | 0.01 |
| q2_s50 | base | 0.20 | 0.20 | 0.03 | 0.01 | · | · | 0.02 | · | · | 0.08 | 0.05 |
| q2_s50 | prenestoff | 0.16 | 0.15 | 0.01 | 0.02 | · | · | 0.03 | · | · | 0.06 | 0.03 |
| q2_s50 | prenest | 0.13 | 0.12 | 0.01 | 0.03 | · | · | 0.02 | · | · | 0.04 | 0.02 |
| q2_s50 | flat | 0.06 | 0.06 | 0.01 | · | 0.03 | · | · | · | · | · | · |
| q2_s50 | pureflat | 0.04 | 0.03 | 0.01 | · | · | · | · | · | 0.01 | 0.01 | 0.01 |
| q3_c11 | base | 0.14 | 0.13 | 0.03 | 0.02 | · | · | 0.04 | · | · | 0.02 | 0.02 |
| q3_c11 | prenestoff | 0.14 | 0.14 | 0.03 | 0.03 | · | · | 0.03 | · | · | 0.03 | 0.01 |
| q3_c11 | prenest | 0.14 | 0.14 | 0.03 | 0.03 | · | · | 0.04 | · | · | 0.03 | 0.02 |
| q3_c11 | flat | 0.12 | 0.11 | 0.04 | · | 0.04 | 0.01 | · | · | 0.01 | · | 0.01 |
| q3_c11 | pureflat | 0.07 | 0.06 | 0.02 | · | · | · | · | · | 0.01 | 0.01 | 0.01 |
| q3_c12 | base | 0.07 | 0.07 | 0.01 | 0.02 | · | · | 0.02 | · | · | 0.01 | 0.01 |
| q3_c12 | prenestoff | 0.07 | 0.07 | 0.01 | 0.01 | · | · | 0.02 | · | · | 0.01 | 0.01 |
| q3_c12 | prenest | 0.07 | 0.07 | 0.01 | 0.01 | · | · | 0.02 | · | · | 0.02 | 0.01 |
| q3_c12 | flat | 0.05 | 0.05 | · | · | 0.03 | 0.01 | · | · | · | · | 0.01 |
| q3_c12 | pureflat | 0.03 | 0.02 | 0.01 | · | · | · | · | · | · | 0.01 | 0.01 |
| q3_c13 | base | 0.06 | 0.06 | 0.01 | 0.01 | · | · | 0.02 | · | · | 0.01 | 0.01 |
| q3_c13 | prenestoff | 0.06 | 0.06 | · | 0.02 | · | · | 0.02 | · | · | 0.01 | 0.01 |
| q3_c13 | prenest | 0.06 | 0.06 | · | 0.01 | · | · | 0.02 | · | · | 0.01 | 0.01 |
| q3_c13 | flat | 0.04 | 0.04 | 0.01 | · | 0.03 | · | · | · | · | · | · |
| q3_c13 | pureflat | 0.02 | 0.01 | 0.01 | · | · | · | · | · | · | · | · |

### 원소당·리스트당 비용 (ns)

범주 시간을 다섯 가지 단위 수로 나눈 값의 평균과, 쿼리 사이의 변동계수 CV(표준편차/평균)입니다.
비용이 그 단위에 비례하면 단위당 비용이 쿼리마다 같아 CV가 작습니다. 판단 = CV가 가장 작은 단위.
단위 수는 위 표의 값이고 flat·pure flat에도 같은 수를 씁니다. 0.01초 미만인 칸은 뺍니다.

| 구성 | 범주 | 쿼리 수 | 파일 리스트 ns (CV) | 스캔한 리스트 ns (CV) | 파일 원소 ns (CV) | 펼친 원소 ns (CV) | 통과 원소 ns (CV) | 판단 |
|---|---|---|---|---|---|---|---|---|
| base | 값 디코드 | 12 | 24.3 (0.34) | 303.1 (3.03) | 6.9 (0.33) | 85.9 (3.03) | 156.8 (1.98) | 파일 원소 |
| base | 리스트 조립 | 12 | 39.8 (0.43) | 419.9 (2.97) | 11.5 (0.41) | 119.1 (2.96) | 266.1 (1.98) | 파일 원소 |
| base | UNNEST | 11 | 13.1 (0.22) | 14.1 (0.21) | 3.8 (0.22) | 4.1 (0.21) | 42.5 (2.32) | 펼친 원소 |
| base | 원소 다루기 | 7 | 22.9 (0.52) | 22.9 (0.52) | 6.4 (0.57) | 6.4 (0.57) | 125.1 (2.00) | 파일 리스트 |
| prenestoff | 값 디코드 | 11 | 13.3 (0.28) | 131.5 (2.81) | 3.7 (0.28) | 37.1 (2.82) | 80.8 (1.82) | 파일 리스트 |
| prenestoff | 리스트 조립 | 12 | 34.7 (0.35) | 360.1 (2.96) | 9.9 (0.34) | 102.1 (2.96) | 235.8 (2.00) | 파일 원소 |
| prenestoff | UNNEST | 11 | 14.4 (0.24) | 15.3 (0.21) | 4.2 (0.25) | 4.5 (0.21) | 45.4 (2.27) | 스캔한 리스트 |
| prenestoff | 원소 다루기 | 6 | 24.3 (0.45) | 24.3 (0.45) | 6.8 (0.50) | 6.8 (0.50) | 114.9 (1.71) | 파일 리스트 |
| prenest | 값 디코드 | 11 | 12.9 (0.25) | 135.5 (2.83) | 3.5 (0.21) | 38.2 (2.85) | 90.5 (1.91) | 파일 원소 |
| prenest | 리스트 조립 | 12 | 27.3 (0.45) | 356.9 (3.04) | 7.8 (0.44) | 101.1 (3.03) | 141.6 (2.21) | 파일 원소 |
| prenest | UNNEST | 10 | 13.2 (0.25) | 14.1 (0.21) | 3.8 (0.25) | 4.1 (0.21) | 10.3 (0.75) | 펼친 원소 |
| prenest | 원소 다루기 | 6 | 12.6 (0.61) | 12.6 (0.61) | 3.7 (0.59) | 3.7 (0.59) | 10.7 (0.63) | 파일 원소 |
| flat | 값 디코드 | 11 | 13.0 (0.41) | 77.2 (2.55) | 3.4 (0.29) | 21.6 (2.58) | 67.5 (1.94) | 파일 원소 |
| flat | 원소 다루기 | 6 | 18.3 (0.40) | 18.3 (0.40) | 5.1 (0.46) | 5.1 (0.46) | 89.9 (1.77) | 파일 리스트 |
| flat | 키 생성 | 12 | 16.5 (0.16) | 182.7 (3.00) | 4.8 (0.19) | 51.9 (2.99) | 105.6 (1.95) | 파일 리스트 |
| flat | join | 3 | 52.0 (0.58) | 567.6 (1.16) | 14.9 (0.58) | 160.9 (1.16) | 160.9 (1.16) | 파일 원소 |
| pureflat | 값 디코드 | 12 | 19.1 (0.54) | 311.2 (3.09) | 5.4 (0.53) | 88.1 (3.09) | 127.8 (2.21) | 파일 원소 |

## 1-3 TPC-H (1스레드, perf)

### 새 기준(call stack): CPU 초, 괄호는 비율(%)

| 데이터 | 쿼리 | 구성 | wall | CPU | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tpch_sf1 | q01 | base | 0.19 | 0.17 | 0.06 (38) | 0.08 (50) | · | · | · | · | 0.01 (7) | · |
| tpch_sf1 | q01 | flat | 0.05 | 0.05 | 0.02 (52) | · | · | · | · | · | 0.01 (24) | · |
| tpch_sf1 | q01 | prenestoff | 0.12 | 0.11 | 0.02 (19) | 0.07 (63) | · | 0.01 (4) | · | · | 0.01 (7) | 0.01 (4) |
| tpch_sf1 | q06 | base | 0.18 | 0.16 | 0.06 (40) | 0.09 (55) | · | · | · | · | · | · |
| tpch_sf1 | q06 | flat | 0.02 | 0.01 | 0.01 (71) | · | · | · | · | · | · | · |
| tpch_sf1 | q06 | prenestoff | 0.10 | 0.09 | 0.01 (11) | 0.07 (78) | · | · | · | · | · | · |
| tpch_sf10 | q01 | base | 0.10 | 0.10 | 0.04 (40) | 0.04 (40) | · | · | · | · | 0.01 (13) | · |
| tpch_sf10 | q01 | flat | 0.02 | 0.02 | 0.01 (70) | · | · | · | · | · | · | · |
| tpch_sf10 | q01 | prenestoff | 0.07 | 0.07 | 0.01 (18) | 0.03 (50) | · | 0.01 (7) | · | · | 0.01 (18) | · |
| tpch_sf10 | q06 | base | 0.10 | 0.09 | 0.04 (42) | 0.04 (49) | · | 0.01 (7) | · | · | · | · |
| tpch_sf10 | q06 | flat | 0.01 | 0.01 | 0.01 (69) | · | · | · | · | · | · | · |
| tpch_sf10 | q06 | prenestoff | 0.05 | 0.05 | 0.01 (19) | 0.03 (64) | · | · | · | · | · | 0.01 (9) |

### 옛 기준(잎 함수 이름): CPU 초, 괄호는 비율(%)

| 데이터 | 쿼리 | 구성 | wall | CPU | 디코드 | 조립 | 키 | FILTER | UNNEST | join | 집계 | 식·벡터 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tpch_sf1 | q01 | base | 0.19 | 0.17 | 0.05 (29) | · | · | · | · | · | · | 0.07 (39) | 0.05 (30) |
| tpch_sf1 | q01 | flat | 0.05 | 0.05 | 0.02 (43) | · | · | · | · | · | · | · | 0.01 (30) |
| tpch_sf1 | q01 | prenestoff | 0.12 | 0.11 | 0.02 (18) | · | · | · | · | · | · | 0.06 (51) | 0.03 (25) |
| tpch_sf1 | q06 | base | 0.18 | 0.16 | 0.05 (32) | · | · | · | · | · | · | 0.07 (43) | 0.04 (22) |
| tpch_sf1 | q06 | flat | 0.02 | 0.01 | 0.01 (43) | · | · | · | · | · | · | · | 0.01 (36) |
| tpch_sf1 | q06 | prenestoff | 0.10 | 0.09 | 0.01 (9) | · | · | · | · | · | · | 0.06 (61) | 0.03 (29) |
| tpch_sf10 | q01 | base | 0.10 | 0.10 | 0.03 (32) | · | · | · | · | · | · | 0.03 (29) | 0.03 (34) |
| tpch_sf10 | q01 | flat | 0.02 | 0.02 | 0.01 (50) | · | · | · | · | · | · | · | 0.01 (25) |
| tpch_sf10 | q01 | prenestoff | 0.07 | 0.07 | 0.01 (15) | · | · | · | · | · | · | 0.03 (40) | 0.03 (40) |
| tpch_sf10 | q06 | base | 0.10 | 0.09 | 0.03 (36) | · | · | · | · | · | · | 0.04 (41) | 0.02 (20) |
| tpch_sf10 | q06 | flat | 0.01 | 0.01 | 0.01 (46) | · | · | · | · | · | · | · | · |
| tpch_sf10 | q06 | prenestoff | 0.05 | 0.05 | · | · | · | · | · | · | · | 0.03 (62) | 0.01 (25) |

## 옛 기준 → 새 기준

같은 perf 샘플을 두 기준으로 나눴습니다. 옛 기준은 잎 함수의 전체 이름(인자 포함)만 보고(`../../profile_breakdown.py`),
새 기준은 call stack을 위로 따라갑니다(`categories.py`). 행 = 옛 열, 열 = 새 범주, 값 = CPU 초.

### q2_s50 base

| 옛 열 \ 새 범주 | 합계 | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|
| 디코드 | 0.03 | 0.03 | · | · | · | · | · | · | · |
| 조립 | 0.01 | · | 0.01 | · | · | · | · | · | · |
| UNNEST | 0.02 | · | · | 0.02 | · | · | · | · | · |
| 식·벡터 | 0.08 | · | 0.06 | · | 0.01 | · | · | · | 0.01 |
| 기타 | 0.05 | 0.02 | 0.03 | · | · | · | · | · | 0.01 |
| 새 범주 합계 | 0.20 | 0.05 | 0.10 | 0.02 | 0.02 | · | · | · | 0.01 |

### q2_s50 prenestoff

| 옛 열 \ 새 범주 | 합계 | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|
| 디코드 | 0.01 | 0.01 | · | · | · | · | · | · | · |
| 조립 | 0.02 | · | 0.02 | · | · | · | · | · | · |
| UNNEST | 0.03 | · | · | 0.03 | · | · | · | · | · |
| 식·벡터 | 0.06 | · | 0.05 | · | 0.01 | · | · | · | · |
| 기타 | 0.03 | · | 0.02 | · | · | · | · | · | 0.01 |
| 새 범주 합계 | 0.15 | 0.01 | 0.09 | 0.03 | 0.01 | · | · | · | 0.01 |

### q2_s50 prenest

| 옛 열 \ 새 범주 | 합계 | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|
| 디코드 | 0.01 | 0.01 | · | · | · | · | · | · | · |
| 조립 | 0.03 | · | 0.03 | · | · | · | · | · | · |
| UNNEST | 0.02 | · | · | 0.02 | · | · | · | · | · |
| 식·벡터 | 0.04 | · | 0.03 | · | 0.01 | · | · | · | · |
| 기타 | 0.02 | 0.01 | 0.01 | · | · | · | · | · | · |
| 새 범주 합계 | 0.12 | 0.02 | 0.07 | 0.03 | 0.01 | · | · | · | · |

### q2_s50 flat

| 옛 열 \ 새 범주 | 합계 | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|
| 디코드 | 0.01 | 0.01 | · | · | · | · | · | · | · |
| 키 | 0.03 | · | · | · | · | 0.03 | · | · | · |
| 새 범주 합계 | 0.06 | 0.02 | · | · | · | 0.03 | · | · | · |

### q2_s50 pureflat

| 옛 열 \ 새 범주 | 합계 | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|
| 디코드 | 0.01 | 0.01 | · | · | · | · | · | · | · |
| 집계 | 0.01 | · | · | · | · | · | · | 0.01 | · |
| 식·벡터 | 0.01 | 0.01 | · | · | · | · | · | · | · |
| 기타 | 0.01 | · | · | · | · | · | · | · | · |
| 새 범주 합계 | 0.03 | 0.02 | · | · | 0.01 | · | · | 0.01 | · |

### q2_s50 prenestoff: 옛 '식·벡터' 0.06초가 가는 곳 (새 범주 / 세부)

지난 보고(`server_20261029/profile/q2_s50.prenestoff.txt`, 다른 실행)의 옛 '식·벡터'는 6.87초(expressions 4.20 + vectors 2.67)였습니다.

| 새 범주 | 세부 | CPU 초 | 비율 | 주요 잎 함수 (초) |
|---|---|---|---|---|
| 리스트 조립 | list/struct reader | 0.05 | 84% | `TemplatedValidityMask<unsigned long>::SetInvalid` 0.03, `VectorStringBuffer::CopyInternal` 0.01, `ValidityMask::CopySel` 0.01, `VectorBuffer::Copy` · |
| 원소 다루기 | FILTER | 0.01 | 9% | `SelectionVector::Slice` ·, `DictionaryBuffer::DictionaryBuffer` ·, `unsigned long ScalarExecutor::SelectOutputDispatch<BinaryExe` ·, `StandardVectorBuffer::GetValidityMask` · |

### 모든 실행: 옛 '식·벡터'가 가는 곳 (상위 3개 새 범주)

| 폴더 | 쿼리 | 구성 | 옛 식·벡터 초 | 새 범주 (초) |
|---|---|---|---|---|
| params | q1_s01 | base | 0.07 | 조립 0.06, 디코드 0.01, 기타 · |
| params | q1_s01 | prenestoff | 0.05 | 조립 0.04, 디코드 ·, 기타 · |
| params | q1_s01 | prenest | 0.05 | 조립 0.05, 디코드 ·, 기타 · |
| params | q1_s01 | flat | 0.01 | 기타 ·, join ·, 디코드 · |
| params | q1_s01 | pureflat | 0.01 | 디코드 0.01, join · |
| params | q1_s50 | base | 0.07 | 조립 0.06, 디코드 ·, UNNEST · |
| params | q1_s50 | prenestoff | 0.05 | 조립 0.04, 기타 ·, 디코드 · |
| params | q1_s50 | prenest | 0.05 | 조립 0.04, 기타 ·, 디코드 · |
| params | q1_s50 | flat | 0.02 | join 0.01, 기타 ·, 디코드 · |
| params | q1_s50 | pureflat | 0.01 | 디코드 0.01, join 0.01, 기타 · |
| params | q1_s90 | base | 0.07 | 조립 0.06, UNNEST 0.01, 디코드 · |
| params | q1_s90 | prenestoff | 0.06 | 조립 0.05, UNNEST ·, 기타 · |
| params | q1_s90 | prenest | 0.05 | 조립 0.04, UNNEST ·, 디코드 · |
| params | q1_s90 | flat | 0.02 | join 0.01, 디코드 0.01, 기타 · |
| params | q1_s90 | pureflat | 0.02 | join 0.01, 디코드 0.01, 기타 · |
| params | q2_c01 | base | 0.09 | 조립 0.06, 원소 0.02, 기타 0.01 |
| params | q2_c01 | prenestoff | 0.06 | 조립 0.04, 원소 0.02, 기타 · |
| params | q2_c01 | prenest | 0.01 | 원소 0.01, 기타 ·, 디코드 · |
| params | q2_c01 | flat | 0.01 | 원소 0.01, 디코드 ·, 기타 · |
| params | q2_c10 | base | 0.09 | 조립 0.06, 원소 0.03, 기타 0.01 |
| params | q2_c10 | prenestoff | 0.08 | 조립 0.04, 원소 0.03, 기타 · |
| params | q2_c10 | prenest | 0.02 | 조립 0.01, 원소 0.01, 디코드 · |
| params | q2_c10 | flat | 0.02 | 원소 0.02, 디코드 · |
| params | q2_c10 | pureflat | 0.01 | 원소 ·, 디코드 ·, 집계 · |
| params | q2_c25 | base | 0.10 | 조립 0.06, 원소 0.04, 디코드 · |
| params | q2_c25 | prenestoff | 0.09 | 조립 0.05, 원소 0.03, 기타 0.01 |
| params | q2_c25 | prenest | 0.03 | 조립 0.02, 원소 0.01, 기타 · |
| params | q2_c25 | flat | 0.01 | 원소 0.01, 디코드 · |
| params | q2_c50 | base | 0.12 | 원소 0.06, 조립 0.05, 디코드 · |
| params | q2_c50 | prenestoff | 0.11 | 원소 0.06, 조립 0.06, 기타 · |
| params | q2_c50 | prenest | 0.05 | 조립 0.03, 원소 0.01, 기타 · |
| params | q2_c50 | flat | 0.02 | 원소 0.02, 디코드 · |
| params | q2_c50 | pureflat | 0.01 | 디코드 0.01, 원소 · |
| params | q2_c75 | base | 0.11 | 조립 0.07, 원소 0.03, 기타 · |
| params | q2_c75 | prenestoff | 0.09 | 조립 0.05, 원소 0.03, UNNEST · |
| params | q2_c75 | prenest | 0.07 | 조립 0.04, 원소 0.02, 기타 · |
| params | q2_c75 | flat | 0.03 | 원소 0.02, 디코드 0.01, 기타 · |
| params | q2_c75 | pureflat | 0.01 | 디코드 0.01, 원소 · |
| params | q2_s50 | base | 0.08 | 조립 0.06, 원소 0.01, 기타 0.01 |
| params | q2_s50 | prenestoff | 0.06 | 조립 0.05, 원소 0.01, 기타 · |
| params | q2_s50 | prenest | 0.04 | 조립 0.03, 원소 0.01, UNNEST · |
| params | q2_s50 | pureflat | 0.01 | 디코드 0.01, 원소 · |
| params | q3_c11 | base | 0.02 | 원소 0.01, 조립 0.01, 기타 · |
| params | q3_c11 | prenestoff | 0.03 | 원소 0.01, 조립 0.01, 기타 · |
| params | q3_c11 | prenest | 0.03 | 조립 0.02, 원소 0.01, 디코드 · |
| params | q3_c11 | pureflat | 0.01 | 디코드 0.01, 원소 ·, 기타 · |
| params | q3_c12 | base | 0.01 | 조립 0.01, 원소 ·, 디코드 · |
| params | q3_c12 | prenestoff | 0.01 | 조립 0.01, 디코드 ·, 원소 · |
| params | q3_c12 | prenest | 0.01 | 원소 0.01, 조립 0.01, 기타 · |
| params | q3_c12 | pureflat | 0.01 | 디코드 ·, 원소 · |
| params | q3_c13 | base | 0.01 | 원소 ·, 조립 ·, 디코드 · |
| params | q3_c13 | prenestoff | 0.01 | 조립 ·, 원소 ·, 집계 · |
| params | q3_c13 | prenest | 0.01 | 조립 ·, 원소 ·, 기타 · |
| stage | s1_box | base | 0.05 | 조립 0.05, 디코드 ·, 집계 · |
| stage | s1_box | prenestoff | 0.07 | 조립 0.07, 디코드 ·, 원소 · |
| stage | s1_box | prenest | 0.08 | 조립 0.07, 디코드 0.01 |
| stage | s2_unnest | base | 0.08 | 조립 0.07, 디코드 ·, 기타 · |
| stage | s2_unnest | prenestoff | 0.06 | 조립 0.06, 디코드 ·, UNNEST · |
| stage | s2_unnest | prenest | 0.06 | 조립 0.06, 디코드 ·, 기타 · |
| stage | s2_unnest | flat | 0.01 | 기타 ·, 디코드 ·, 원소 · |
| stage | s2_unnest | pureflat | 0.01 | 디코드 ·, 기타 ·, 집계 · |
| stage | s2f_fields | base | 0.06 | 조립 0.06, 기타 ·, 디코드 · |
| stage | s2f_fields | prenestoff | 0.06 | 조립 0.05, 원소 ·, UNNEST · |
| stage | s2f_fields | prenest | 0.05 | 조립 0.05, 디코드 ·, UNNEST · |
| stage | s3_cond | base | 0.11 | 조립 0.05, 원소 0.05, 디코드 0.01 |
| stage | s3_cond | prenestoff | 0.09 | 조립 0.05, 원소 0.04, 기타 · |
| stage | s3_cond | prenest | 0.06 | 조립 0.03, 원소 0.02, 디코드 · |
| stage | s3_cond | flat | 0.02 | 원소 0.02, 디코드 · |
| stage | s3_cond | pureflat | 0.01 | 디코드 0.01, 원소 ·, 집계 · |
| tpch_sf1 | q01 | base | 0.07 | 조립 0.06, 원소 ·, 디코드 · |
| tpch_sf1 | q01 | prenestoff | 0.06 | 조립 0.05, 원소 ·, 기타 · |
| tpch_sf1 | q06 | base | 0.07 | 조립 0.07, 원소 · |
| tpch_sf1 | q06 | prenestoff | 0.06 | 조립 0.05, 원소 ·, 기타 · |
| tpch_sf10 | q01 | base | 0.03 | 조립 0.03, 원소 ·, 집계 · |
| tpch_sf10 | q01 | prenestoff | 0.03 | 조립 0.03, UNNEST ·, 원소 · |
| tpch_sf10 | q06 | base | 0.04 | 조립 0.03, 원소 · |
| tpch_sf10 | q06 | prenestoff | 0.03 | 조립 0.03, 기타 ·, 원소 · |

## 1-4 범주 정의

perf 샘플마다 호출 스택을 잎(샘플된 함수)에서 위로 따라가며, 아래 규칙에 처음 맞는 함수가 범주를 정합니다.
규칙에 없는 함수(memcpy·malloc, kernel, validity·벡터 도우미, 해시, tuple data, 문자열 연산)는 건너뛰고, 그것을 부른 코드의 범주를 받습니다.
'임시' 규칙(식 평가)은 위쪽에서 연산자(FILTER, PROJECTION, 스캔 필터, prenest, join, 집계)를 만나면 그 연산자를 따릅니다.
함수 이름은 인자를 뺀 이름으로 맞춥니다. 원본 스택은 `profile/*/*.folded.gz`에 있어 `categories.py classify`로 다시 나눌 수 있습니다.

| 순서 | 범주 | 세부 | 종류 | 함수 이름 패턴 (정규식, 인자 제외) |
|---|---|---|---|---|
| 1 | 원소 다루기 | prenest 조건 | 확정 | `PrenestFilter` |
| 2 | join | join 필터 | 확정 | `JoinFilterPushdown &#124; BloomFilter &#124; PrefixRange &#124; PerfectHashJoinFilter &#124; DynamicTableFilterSet &#124; PushDynamicFilters` |
| 3 | 원소 다루기 | 스캔 필터 | 확정 | `(?<![A-Za-z])ColumnReader::(Select &#124; Filter &#124; ApplyFilter) &#124; FilterSelection &#124; TableFilterState &#124; ExpressionFilter &#124; ConstantFilter &#124; ConjunctionAndFilter &#124; ConjunctionOrFilter &#124; IsNotNullFilter &#124; IsNullFilter &#124; FilterRows &#124; TemplatedFilterOperation &#124; ParquetReader::ApplyFilter &#124; ColumnReader::DirectSelect &#124; PlainSelect` |
| 4 | 리스트 조립 | list/struct reader | 확정 | `(List &#124; Struct &#124; Array)ColumnReader &#124; TemplatedListReader &#124; ListReader` |
| 5 | 키 생성 | node keys | 확정 | `ParquetNodeKeyGenerator &#124; CountPageLevelRows &#124; ParquetNodeRowGroupRows &#124; KeyRange` |
| 6 | 값 디코드 | levels/skip | 확정 | `ReadLevels &#124; SkipPageValues &#124; ApplyPendingSkips &#124; PlainSkip &#124; (?<![A-Za-z])ColumnReader::Skip &#124; RleBpDecoder` |
| 7 | 값 디코드 | decode | 확정 | `Decoder &#124; Decompress &#124; [Ss]nappy &#124; ZSTD &#124; zstd &#124; [Ll][Zz]4 &#124; brotli &#124; miniz &#124; BitpackingPrimitives &#124; ParquetDecodeUtils &#124; thrift &#124; Thrift &#124; TCompactProtocol &#124; ColumnReader &#124; ResizeableBuffer &#124; ByteBuffer &#124; DictionaryDecoder` |
| 8 | 값 디코드 | scan | 확정 | `ParquetReader &#124; ParquetScan &#124; ParquetMultiFile &#124; MultiFileFunction &#124; MultiFileReader &#124; PhysicalTableScan &#124; TableScanFunction &#124; ReadParquetNode &#124; ReadParquetFlat &#124; ParquetNodePageCache &#124; ParquetFileMetadataCache` |
| 9 | UNNEST | unnest | 확정 | `PhysicalUnnest &#124; UnnestOperator &#124; UnnestFunction` |
| 10 | join | hash join | 확정 | `PhysicalHashJoin &#124; JoinHashTable &#124; PerfectHashJoin &#124; ScanStructure &#124; PhysicalNestedLoopJoin &#124; PhysicalPiecewiseMergeJoin &#124; PhysicalIEJoin &#124; PhysicalCrossProduct &#124; PhysicalPositionalScan &#124; PhysicalRangeJoin &#124; PhysicalDelimJoin &#124; RowMatcher &#124; JoinHT` |
| 11 | 집계 | aggregate | 확정 | `PhysicalHashAggregate &#124; PhysicalUngroupedAggregate &#124; PhysicalPerfectHashAggregate &#124; RadixPartitionedHashTable &#124; GroupedAggregateHashTable &#124; PerfectAggregateHashTable &#124; AggregateExecutor &#124; AggregateFunction &#124; SumState &#124; AvgState &#124; CountStar &#124; CountFunction &#124; MinMaxState &#124; DistinctAggregate &#124; RadixHTGlobal &#124; RadixHTLocal &#124; AggregateHT` |
| 12 | 원소 다루기 | FILTER | 확정 | `PhysicalFilter` |
| 13 | 원소 다루기 | PROJECTION | 확정 | `PhysicalProjection` |
| 14 | 기타 | 정렬/limit | 확정 | `PhysicalOrder &#124; PhysicalTopN &#124; PhysicalLimit &#124; PhysicalStreamingLimit &#124; RadixSort &#124; SortedRun` |
| 15 | 기타 | 실행기/결과 | 확정 | `PipelineExecutor &#124; TaskScheduler &#124; ExecutorTask &#124; PipelineTask &#124; (?<![A-Za-z])Executor:: &#124; PhysicalResultCollector &#124; ColumnDataCollection &#124; QueryResult &#124; ClientContext &#124; duckdb_shell &#124; ShellState` |
| 16 | 원소 다루기 | 식 | 임시 (위쪽 연산자가 정함) | `ExpressionExecutor &#124; BinaryExecutor &#124; UnaryExecutor &#124; TernaryExecutor &#124; GenericExecutor &#124; ScalarFunction &#124; StructExtract &#124; ListExtract &#124; VectorCastHelpers &#124; TryCast &#124; CastFunction &#124; Comparison &#124; LikeOperator &#124; ConjunctionState` |
| - | 기타 | libc / kernel / unknown / duckdb 미분류 | 규칙 없음 | 스택 전체에 맞는 규칙이 없을 때, 잎 함수의 종류 |

### 잘린 스택

perf가 스레드 시작까지 풀지 못한 스택(맨 위 프레임이 `[heap]`·`[stack]`·`[unknown]` 주소)입니다. 잘린 아래쪽에서 확정 규칙을 만나면 그 범주를 쓰고,
못 만나면 같은 실행에서 같은 잎 함수를 가진 온전한 샘플들의 범주 비율로 나눕니다(그런 샘플이 없으면 기타/잘린 스택).

실행 92개: 중앙값 0.5%, 최댓값 3.6%. 5%를 넘는 실행:


### '기타'가 10%를 넘는 실행

- stage s1_box pureflat: 기타 11% (실행기/결과 ·)
  - 1 ms `duckdb::DBConfig::TryGetSettingIndex`
  - 1 ms `duckdb::PipelineExecutor::EndOperator`
  - 1 ms `_IO_file_sync`

### 문자열 복사·validity 함수를 부른 곳 (q2_s50)

범주/세부, 그리고 그 함수 위의 세 프레임.

**q2_s50 base**

```
  VectorStringBuffer::CopyInternal: 39 ms
        38 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
         1 ms  값 디코드/decode  < VectorBuffer::Copy < VectorOperations::Copy < DictionaryDecoder::Read
  SelectionVector::Slice: 1 ms
         1 ms  원소 다루기/FILTER  < DictionaryBuffer::SliceInternal < VectorBuffer::Slice < Vector::Slice
  ValidityMask::CopySel: 19 ms
        17 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
         1 ms  값 디코드/decode  < StandardVectorBuffer::FlattenSliceInternal < VectorStringBuffer::FlattenSliceInternal < VectorBuffer::FlattenSlice
         1 ms  UNNEST/unnest  < VectorStructBuffer::VectorStructBuffer < VectorStructBuffer::SliceInternal < VectorBuffer::Slice
  VectorBuffer::Copy: 5 ms
         5 ms  리스트 조립/list/struct reader  < VectorStructBuffer::CopyInternal < VectorBuffer::Copy < VectorBuffer::Append
```

**q2_s50 prenestoff**

```
  TemplatedValidityMask<unsigned long>::SetInvalid: 27 ms
        27 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  VectorStringBuffer::CopyInternal: 10 ms
        10 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  SelectionVector::Slice: 2 ms
         2 ms  원소 다루기/FILTER  < DictionaryBuffer::SliceInternal < VectorBuffer::Slice < Vector::Slice
  VectorBuffer::Copy: 6 ms
         4 ms  리스트 조립/list/struct reader  < VectorStructBuffer::CopyInternal < VectorBuffer::Copy < VectorBuffer::Append
         2 ms  리스트 조립/list/struct reader  < VectorBuffer::Append < unsigned long ListColumnReader::ReadInternal<TemplatedListReader> < ParquetReader::Process
  ValidityMask::CopySel: 5 ms
         5 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
```

**q2_s50 prenest**

```
  VectorStringBuffer::CopyInternal: 8 ms
         8 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  SelectionVector::Slice: 1 ms
         1 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  VectorBuffer::Copy: 3 ms
         3 ms  리스트 조립/list/struct reader  < VectorStructBuffer::CopyInternal < VectorBuffer::Copy < VectorBuffer::Append
  TemplatedValidityMask<unsigned long>::SetInvalid: 12 ms
        12 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  ValidityMask::CopySel: 4 ms
         4 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
```

**q2_s50 pureflat**

```
  SelectionVector::Slice: 2 ms
         2 ms  값 디코드/scan  < DictionaryBuffer::SliceInternal < VectorBuffer::Slice < DictionaryBuffer::SliceWithCache
  ValidityMask::CopySel: 3 ms
         2 ms  값 디코드/decode  < StandardVectorBuffer::FlattenSliceInternal < VectorBuffer::FlattenSlice < DictionaryBuffer::Flatten
         1 ms  값 디코드/decode  < VectorBuffer::Copy < VectorOperations::Copy < DictionaryDecoder::Read
```

