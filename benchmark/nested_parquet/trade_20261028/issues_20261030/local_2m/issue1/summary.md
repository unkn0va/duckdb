# 이슈 1: Unnest 오버헤드 분해 (issue1_2m)

```
date:     2026-10-30T14:03:23+09:00
host:     ChoiLY, 20 hardware threads, 15 GiB memory
cpu:      Intel(R) Core(TM) i5-14500
uptime:    14:03:23 up 3 days,  1:10,  1 user,  load average: 0.13, 0.28, 0.30
base:     v2.1.0-dev88383 a809d3cd51  /home/layun03/nested-bench/duckdb_base/build/release/duckdb
prenest:  v2.1.0-dev88385 fabde05fe6  /home/layun03/nested-bench/duckdb_prenest_base/build/release/duckdb
final:    v2.1.0-dev88419 2d345279c3  /home/layun03/nested-bench/duckdb_rey/build/release/duckdb
perf:     perf version 6.8.12  (perf)
scripts:  69bd3cab48b nested_parquet: trade recheck with the float tolerance passes on apache10
data:     <2백만 행 샘플>/full
runs:     3, perf 1000 Hz
```

## 1-1 단계 누적 쿼리 (legs, 1스레드)

단계: s1 상자(목록만) → s2 펼치기(count) → s2f 펼치기 + s3에서 쓰는 필드 2개 → s3 q2_c50 조건과 합계.
flat·pure flat에는 상자가 없어 s1은 키만 읽고, s2와 s2f는 같은 쿼리입니다. 쿼리는 `queries_stage/`, 계획 확인은 `stage_check.md`.

### 시간 (초, RUNS 중 최소) / 결과 일치

| 구성 | s1_box | s2_unnest | s2f_fields | s3_cond |
|---|---|---|---|---|
| base | 0.153 (yes) | 0.182 (yes) | 0.191 (yes) | 0.267 (yes) |
| prenestoff | 0.152 (yes) | 0.188 (yes) | 0.157 (yes) | 0.225 (yes) |
| prenest | 0.154 (yes) | 0.186 (yes) | 0.151 (yes) | 0.172 (yes) |
| flat | 0.046 (yes) | 0.072 (yes) | 0.065 (yes) | 0.125 (yes) |
| pureflat | 0.033 (yes) | 0.039 (yes) | 0.040 (yes) | 0.056 (yes) |

### perf 범주 (CPU 초)

| 구성 | 단계 | wall | CPU | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base | s1_box | 0.16 | 0.15 | 0.05 | 0.10 | · | · | · | · | · | · |
| base | s2_unnest | 0.19 | 0.18 | 0.04 | 0.10 | 0.03 | · | · | · | · | 0.01 |
| base | s2f_fields | 0.20 | 0.19 | 0.06 | 0.08 | 0.03 | 0.01 | · | · | · | · |
| base | s3_cond | 0.28 | 0.27 | 0.06 | 0.10 | 0.03 | 0.08 | · | · | · | 0.01 |
| prenestoff | s1_box | 0.17 | 0.16 | 0.05 | 0.11 | · | · | · | · | · | · |
| prenestoff | s2_unnest | 0.19 | 0.18 | 0.05 | 0.10 | 0.03 | · | · | · | · | · |
| prenestoff | s2f_fields | 0.15 | 0.14 | 0.02 | 0.09 | 0.02 | 0.01 | · | · | · | · |
| prenestoff | s3_cond | 0.25 | 0.24 | 0.03 | 0.09 | 0.03 | 0.07 | · | · | 0.01 | 0.01 |
| prenest | s1_box | 0.17 | 0.17 | 0.06 | 0.10 | · | · | · | · | · | · |
| prenest | s2_unnest | 0.19 | 0.19 | 0.05 | 0.10 | 0.04 | · | · | · | · | · |
| prenest | s2f_fields | 0.15 | 0.15 | 0.02 | 0.08 | 0.04 | · | · | · | · | 0.01 |
| prenest | s3_cond | 0.18 | 0.17 | 0.02 | 0.07 | 0.03 | 0.04 | · | · | 0.01 | · |
| flat | s1_box | 0.05 | 0.05 | 0.01 | · | · | · | 0.03 | · | · | · |
| flat | s2_unnest | 0.07 | 0.07 | 0.04 | · | · | · | 0.03 | · | 0.01 | · |
| flat | s2f_fields | 0.07 | 0.07 | 0.03 | · | · | · | 0.03 | · | · | · |
| flat | s3_cond | 0.14 | 0.14 | 0.04 | · | · | 0.06 | 0.03 | · | 0.01 | · |
| pureflat | s1_box | 0.04 | 0.03 | 0.02 | · | · | · | · | · | · | · |
| pureflat | s2_unnest | 0.04 | 0.03 | 0.03 | · | · | · | · | · | 0.01 | · |
| pureflat | s2f_fields | 0.05 | 0.03 | 0.02 | · | · | · | · | · | 0.01 | · |
| pureflat | s3_cond | 0.06 | 0.05 | 0.04 | · | · | · | · | · | · | · |

### 단계 사이의 차이: 측정 시간 차이 vs perf 범주 차이 (초)

Δwall은 stage_time.csv(최소 시간)의 차이, 나머지는 perf 실행 한 번의 범주별 CPU 차이입니다.
기대: s1→s2는 UNNEST, s2→s2f는 (가지치기하는 구성에서) 디코드·조립 감소 + 필드 꺼내기, s2f→s3는 원소 다루기(조건)와 집계.

| 구성 | 단계 | Δwall | ΔCPU(perf) | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base | s1→s2 | 0.03 | 0.02 | -0.01 | · | 0.03 | · | · | · | · | 0.01 |
| base | s2→s2f | 0.01 | 0.01 | 0.02 | -0.02 | · | 0.01 | · | · | · | · |
| base | s2f→s3 | 0.08 | 0.08 | -0.01 | 0.01 | · | 0.07 | · | · | · | · |
| prenestoff | s1→s2 | 0.04 | 0.02 | 0.01 | -0.01 | 0.03 | · | · | · | · | · |
| prenestoff | s2→s2f | -0.03 | -0.04 | -0.03 | -0.01 | -0.01 | · | · | · | · | · |
| prenestoff | s2f→s3 | 0.07 | 0.10 | 0.01 | · | 0.01 | 0.07 | · | · | 0.01 | 0.01 |
| prenest | s1→s2 | 0.03 | 0.02 | -0.01 | · | 0.04 | · | · | · | · | · |
| prenest | s2→s2f | -0.04 | -0.04 | -0.02 | -0.02 | · | · | · | · | · | · |
| prenest | s2f→s3 | 0.02 | 0.02 | · | -0.01 | · | 0.04 | · | · | · | · |
| flat | s1→s2 | 0.03 | 0.02 | 0.02 | · | · | · | -0.01 | · | 0.01 | · |
| flat | s2→s2f | -0.01 | · | · | · | · | · | · | · | · | · |
| flat | s2f→s3 | 0.06 | 0.07 | · | · | · | 0.06 | 0.01 | · | · | · |
| pureflat | s1→s2 | 0.01 | · | · | · | · | · | · | · | · | · |
| pureflat | s2→s2f | · | · | -0.01 | · | · | · | · | · | 0.01 | · |
| pureflat | s2f→s3 | 0.02 | 0.01 | 0.02 | · | · | · | · | · | -0.01 | · |

## 1-2 파라미터별 분해 (1스레드, perf)

### 리스트와 원소 수 (base EXPLAIN ANALYZE와 파일)

| 쿼리 | 열 | 리스트 (파일 행) | 원소 (파일) | 스캔이 낸 리스트 | UNNEST 원소 | 통과 원소 |
|---|---|---|---|---|---|---|
| q2_c01 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 65,358 |
| q2_c10 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 707,874 |
| q2_c25 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 1,758,205 |
| q2_c50 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 3,492,296 |
| q2_c75 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 5,273,310 |
| q3_c13 | c13 | 2,000,000 | 3,847,601 | 2,000,000 | 3,847,601 | 2,066,564 |
| q3_c12 | c12 | 2,000,000 | 5,596,070 | 2,000,000 | 5,596,070 | 2,806,579 |
| q3_c11 | c11 | 2,000,000 | 13,345,090 | 2,000,000 | 13,345,090 | 6,683,642 |
| q1_s01 | legs | 2,000,000 | 6,997,998 | 20,000 | 70,600 | 70,600 |
| q1_s50 | legs | 2,000,000 | 6,997,998 | 1,001,369 | 3,504,198 | 3,504,198 |
| q1_s90 | legs | 2,000,000 | 6,997,998 | 1,801,509 | 6,304,074 | 6,304,074 |
| q2_s50 | legs | 2,000,000 | 6,997,998 | 2,000,000 | 6,997,998 | 3,504,198 |

### 범주별 CPU 초

| 쿼리 | 구성 | wall | CPU | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| q2_c01 | base | 0.24 | 0.23 | 0.06 | 0.10 | 0.03 | 0.04 | · | · | · | · |
| q2_c01 | prenestoff | 0.19 | 0.19 | 0.03 | 0.07 | 0.04 | 0.03 | · | · | · | 0.01 |
| q2_c01 | prenest | 0.09 | 0.08 | 0.03 | 0.03 | 0.01 | 0.01 | · | · | · | 0.01 |
| q2_c01 | flat | 0.11 | 0.11 | 0.04 | · | · | 0.04 | 0.03 | · | · | · |
| q2_c01 | pureflat | 0.04 | 0.03 | 0.03 | · | · | · | · | · | · | · |
| q2_c10 | base | 0.26 | 0.25 | 0.05 | 0.10 | 0.03 | 0.06 | · | · | 0.01 | 0.01 |
| q2_c10 | prenestoff | 0.20 | 0.20 | 0.03 | 0.07 | 0.03 | 0.06 | · | · | · | 0.01 |
| q2_c10 | prenest | 0.11 | 0.10 | 0.04 | 0.03 | 0.02 | 0.01 | · | · | · | · |
| q2_c10 | flat | 0.11 | 0.11 | 0.03 | · | · | 0.03 | 0.04 | · | · | · |
| q2_c10 | pureflat | 0.04 | 0.04 | 0.03 | · | · | · | · | · | · | · |
| q2_c25 | base | 0.24 | 0.24 | 0.05 | 0.10 | 0.03 | 0.05 | · | · | · | · |
| q2_c25 | prenestoff | 0.20 | 0.19 | 0.02 | 0.08 | 0.04 | 0.04 | · | · | · | 0.01 |
| q2_c25 | prenest | 0.14 | 0.13 | 0.04 | 0.05 | 0.02 | 0.03 | · | · | · | · |
| q2_c25 | flat | 0.10 | 0.10 | 0.04 | · | · | 0.03 | 0.03 | · | · | · |
| q2_c25 | pureflat | 0.04 | 0.04 | 0.02 | · | · | 0.01 | · | · | · | · |
| q2_c50 | base | 0.28 | 0.27 | 0.06 | 0.10 | 0.02 | 0.09 | · | · | · | 0.01 |
| q2_c50 | prenestoff | 0.23 | 0.23 | 0.04 | 0.08 | 0.03 | 0.08 | · | · | · | 0.01 |
| q2_c50 | prenest | 0.17 | 0.16 | 0.03 | 0.08 | 0.03 | 0.02 | · | · | · | · |
| q2_c50 | flat | 0.13 | 0.13 | 0.04 | · | · | 0.07 | 0.02 | · | 0.01 | · |
| q2_c50 | pureflat | 0.05 | 0.04 | 0.03 | · | · | 0.01 | · | · | · | · |
| q2_c75 | base | 0.27 | 0.26 | 0.05 | 0.10 | 0.03 | 0.07 | · | · | 0.01 | 0.01 |
| q2_c75 | prenestoff | 0.22 | 0.22 | 0.03 | 0.09 | 0.03 | 0.07 | · | · | · | 0.01 |
| q2_c75 | prenest | 0.20 | 0.19 | 0.04 | 0.08 | 0.03 | 0.05 | · | · | · | · |
| q2_c75 | flat | 0.13 | 0.13 | 0.04 | · | · | 0.05 | 0.03 | · | 0.01 | · |
| q2_c75 | pureflat | 0.06 | 0.04 | 0.03 | · | · | 0.01 | · | · | 0.01 | · |
| q3_c13 | base | 0.06 | 0.06 | 0.01 | 0.01 | 0.02 | 0.01 | · | · | · | · |
| q3_c13 | prenestoff | 0.06 | 0.06 | 0.01 | 0.02 | 0.02 | 0.01 | · | · | · | · |
| q3_c13 | prenest | 0.06 | 0.06 | 0.01 | 0.02 | 0.03 | · | · | · | · | · |
| q3_c13 | flat | 0.04 | 0.04 | 0.01 | · | · | · | 0.02 | · | 0.01 | · |
| q3_c13 | pureflat | 0.01 | 0.01 | 0.01 | · | · | · | · | · | · | · |
| q3_c12 | base | 0.07 | 0.07 | 0.02 | 0.02 | 0.02 | 0.01 | · | · | · | · |
| q3_c12 | prenestoff | 0.07 | 0.07 | 0.01 | 0.02 | 0.03 | · | · | · | · | · |
| q3_c12 | prenest | 0.07 | 0.07 | 0.02 | 0.03 | 0.02 | · | · | · | · | · |
| q3_c12 | flat | 0.06 | 0.05 | 0.01 | · | · | 0.01 | 0.03 | · | · | · |
| q3_c12 | pureflat | 0.03 | 0.02 | 0.01 | · | · | · | · | · | 0.01 | · |
| q3_c11 | base | 0.14 | 0.14 | 0.04 | 0.05 | 0.03 | 0.01 | · | · | · | 0.01 |
| q3_c11 | prenestoff | 0.14 | 0.14 | 0.05 | 0.04 | 0.04 | 0.01 | · | · | · | · |
| q3_c11 | prenest | 0.14 | 0.14 | 0.04 | 0.05 | 0.04 | 0.01 | · | · | · | · |
| q3_c11 | flat | 0.12 | 0.12 | 0.05 | · | · | 0.01 | 0.05 | · | 0.01 | · |
| q3_c11 | pureflat | 0.07 | 0.06 | 0.03 | · | · | 0.01 | · | · | 0.02 | · |
| q1_s01 | base | 0.18 | 0.17 | 0.06 | 0.10 | · | · | · | · | · | · |
| q1_s01 | prenestoff | 0.12 | 0.12 | 0.02 | 0.08 | · | · | · | · | · | 0.01 |
| q1_s01 | prenest | 0.12 | 0.11 | 0.03 | 0.08 | · | · | · | · | · | · |
| q1_s01 | flat | 0.09 | 0.09 | 0.02 | · | · | · | 0.03 | 0.03 | · | 0.01 |
| q1_s01 | pureflat | 0.09 | 0.08 | 0.07 | · | · | · | · | 0.01 | · | · |
| q1_s50 | base | 0.20 | 0.19 | 0.06 | 0.10 | 0.02 | · | · | · | · | · |
| q1_s50 | prenestoff | 0.14 | 0.14 | 0.03 | 0.09 | 0.01 | · | · | · | · | · |
| q1_s50 | prenest | 0.15 | 0.14 | 0.03 | 0.09 | 0.02 | · | · | · | · | · |
| q1_s50 | flat | 0.18 | 0.18 | 0.03 | · | · | · | 0.03 | 0.10 | 0.01 | · |
| q1_s50 | pureflat | 0.20 | 0.20 | 0.08 | · | · | · | · | 0.11 | 0.01 | · |
| q1_s90 | base | 0.21 | 0.20 | 0.06 | 0.10 | 0.03 | · | · | · | 0.01 | · |
| q1_s90 | prenestoff | 0.16 | 0.15 | 0.02 | 0.09 | 0.02 | · | · | · | · | 0.01 |
| q1_s90 | prenest | 0.16 | 0.16 | 0.03 | 0.09 | 0.03 | · | · | · | · | · |
| q1_s90 | flat | 0.27 | 0.26 | 0.02 | · | · | · | 0.04 | 0.18 | 0.01 | · |
| q1_s90 | pureflat | 0.28 | 0.26 | 0.07 | · | · | · | · | 0.18 | 0.01 | · |
| q2_s50 | base | 0.21 | 0.21 | 0.04 | 0.11 | 0.03 | 0.01 | · | · | · | 0.01 |
| q2_s50 | prenestoff | 0.16 | 0.15 | 0.02 | 0.09 | 0.03 | 0.01 | · | · | · | · |
| q2_s50 | prenest | 0.13 | 0.12 | 0.02 | 0.06 | 0.02 | 0.01 | · | · | · | · |
| q2_s50 | flat | 0.06 | 0.06 | 0.02 | · | · | · | 0.04 | · | · | · |
| q2_s50 | pureflat | 0.04 | 0.03 | 0.02 | · | · | 0.01 | · | · | · | · |

### 원소당·리스트당 비용 (ns)

범주 시간을 다섯 가지 단위 수로 나눈 값의 평균과, 쿼리 사이의 변동계수 CV(표준편차/평균)입니다.
비용이 그 단위에 비례하면 단위당 비용이 쿼리마다 같아 CV가 작습니다. 판단 = CV가 가장 작은 단위.
단위 수는 위 표의 값이고 flat·pure flat에도 같은 수를 씁니다. 0.01초 미만인 칸은 뺍니다.

| 구성 | 범주 | 쿼리 수 | 파일 리스트 ns (CV) | 스캔한 리스트 ns (CV) | 파일 원소 ns (CV) | 펼친 원소 ns (CV) | 통과 원소 ns (CV) | 판단 |
|---|---|---|---|---|---|---|---|---|
| base | 값 디코드 | 12 | 23.2 (0.34) | 269.5 (3.00) | 6.6 (0.32) | 76.4 (3.00) | 154.7 (1.98) | 파일 원소 |
| base | 리스트 조립 | 12 | 41.0 (0.39) | 445.6 (2.98) | 11.6 (0.39) | 126.2 (2.98) | 268.2 (1.96) | 파일 리스트 |
| base | UNNEST | 11 | 13.0 (0.17) | 13.9 (0.17) | 3.8 (0.24) | 4.1 (0.22) | 51.2 (2.53) | 스캔한 리스트 |
| base | 원소 다루기 | 6 | 26.4 (0.42) | 26.4 (0.42) | 7.5 (0.42) | 7.5 (0.42) | 127.4 (1.71) | 파일 원소 |
| prenestoff | 값 디코드 | 10 | 14.3 (0.27) | 139.6 (2.65) | 3.8 (0.19) | 39.3 (2.67) | 96.7 (1.80) | 파일 원소 |
| prenestoff | 리스트 조립 | 12 | 35.0 (0.35) | 369.2 (2.97) | 10.1 (0.33) | 104.7 (2.96) | 209.9 (1.94) | 파일 원소 |
| prenestoff | UNNEST | 11 | 14.0 (0.26) | 14.7 (0.18) | 4.1 (0.25) | 4.3 (0.18) | 64.9 (2.60) | 펼친 원소 |
| prenestoff | 원소 다루기 | 6 | 23.5 (0.47) | 23.5 (0.47) | 6.7 (0.47) | 6.7 (0.47) | 107.1 (1.68) | 파일 리스트 |
| prenest | 값 디코드 | 11 | 14.8 (0.24) | 142.3 (2.80) | 4.0 (0.21) | 40.1 (2.81) | 86.8 (1.82) | 파일 원소 |
| prenest | 리스트 조립 | 12 | 28.2 (0.45) | 358.3 (3.02) | 8.1 (0.44) | 101.6 (3.02) | 143.8 (2.18) | 파일 원소 |
| prenest | UNNEST | 10 | 12.3 (0.24) | 13.4 (0.24) | 3.7 (0.35) | 4.0 (0.32) | 9.4 (0.72) | 스캔한 리스트 |
| prenest | 원소 다루기 | 7 | 10.9 (0.58) | 10.9 (0.58) | 3.0 (0.64) | 3.0 (0.64) | 36.5 (1.82) | 파일 리스트 |
| flat | 값 디코드 | 12 | 14.8 (0.38) | 111.1 (2.82) | 4.1 (0.30) | 31.4 (2.83) | 84.0 (2.02) | 파일 원소 |
| flat | 원소 다루기 | 6 | 18.4 (0.44) | 18.4 (0.44) | 5.1 (0.50) | 5.1 (0.50) | 111.9 (1.88) | 파일 리스트 |
| flat | 키 생성 | 12 | 16.0 (0.25) | 133.0 (2.87) | 4.6 (0.19) | 37.7 (2.87) | 86.8 (1.90) | 파일 원소 |
| flat | join | 3 | 53.7 (0.58) | 618.8 (1.18) | 15.3 (0.58) | 175.5 (1.18) | 175.5 (1.18) | 파일 리스트 |
| pureflat | 값 디코드 | 11 | 19.5 (0.54) | 329.4 (2.95) | 5.4 (0.58) | 93.2 (2.95) | 140.1 (2.07) | 파일 리스트 |

## 1-3 TPC-H (1스레드, perf)

CPU 초, 괄호는 비율(%).

| 데이터 | 쿼리 | 구성 | wall | CPU | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tpch_sf1 | q01 | base | 0.17 | 0.15 | 0.06 (38) | 0.07 (49) | · | · | · | · | 0.01 (7) | 0.01 (3) |
| tpch_sf1 | q01 | prenestoff | 0.13 | 0.11 | 0.02 (21) | 0.07 (62) | · | 0.01 (5) | · | · | 0.01 (8) | · |
| tpch_sf1 | q01 | flat | 0.04 | 0.04 | 0.02 (56) | · | · | 0.01 (14) | · | · | 0.01 (23) | · |
| tpch_sf1 | q06 | base | 0.16 | 0.14 | 0.06 (43) | 0.07 (50) | · | 0.01 (4) | · | · | · | · |
| tpch_sf1 | q06 | prenestoff | 0.11 | 0.09 | 0.01 (13) | 0.07 (80) | · | 0.01 (6) | · | · | · | · |
| tpch_sf1 | q06 | flat | 0.02 | 0.01 | 0.01 (64) | · | · | · | · | · | · | · |
| tpch_sf10 | q01 | base | 0.11 | 0.10 | 0.04 (37) | 0.04 (40) | · | 0.01 (7) | · | · | 0.01 (10) | · |
| tpch_sf10 | q01 | prenestoff | 0.07 | 0.07 | 0.01 (17) | 0.03 (51) | · | 0.01 (14) | · | · | 0.01 (8) | · |
| tpch_sf10 | q01 | flat | 0.02 | 0.02 | 0.01 (48) | · | · | 0.01 (24) | · | · | · | · |
| tpch_sf10 | q06 | base | 0.12 | 0.11 | 0.04 (40) | 0.06 (52) | · | 0.01 (5) | · | · | · | · |
| tpch_sf10 | q06 | prenestoff | 0.06 | 0.06 | 0.01 (11) | 0.04 (75) | · | 0.01 (9) | · | · | · | · |
| tpch_sf10 | q06 | flat | 0.01 | 0.01 | 0.01 (54) | · | · | · | · | · | · | · |

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

### '기타'가 10%를 넘는 실행

- params q3_c13 pureflat: 기타 17% (실행기/결과 ·)
  - 1 ms `[unknown]`
  - 1 ms `duckdb::VectorBuffer::ClearAuxiliaryData`
- tpch_sf10 q06 flat: 기타 15% (실행기/결과 ·)
  - 1 ms `duckdb::operator==`
  - 1 ms `duckdb::Executor::ScheduleEvents`

### 문자열 복사·validity 함수를 부른 곳 (q2_s50)

범주/세부, 그리고 그 함수 위의 세 프레임.

**q2_s50 base**

```
  ValidityMask::CopySel: 23 ms
        22 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
         1 ms  값 디코드/decode  < VectorBuffer::Copy < VectorOperations::Copy < DictionaryDecoder::Read
  VectorStringBuffer::CopyInternal: 44 ms
        43 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
         1 ms  값 디코드/decode  < VectorBuffer::Copy < VectorOperations::Copy < DictionaryDecoder::Read
  VectorBuffer::Copy: 9 ms
         7 ms  리스트 조립/list/struct reader  < VectorStructBuffer::CopyInternal < VectorBuffer::Copy < VectorBuffer::Append
         2 ms  값 디코드/decode  < VectorOperations::Copy < DictionaryDecoder::Read < ColumnReader::ReadData
  SelectionVector::Slice: 3 ms
         2 ms  원소 다루기/FILTER  < DictionaryBuffer::SliceInternal < VectorBuffer::Slice < Vector::Slice
         1 ms  원소 다루기/FILTER  < DictionaryBuffer::SliceInternal < VectorBuffer::Slice < DictionaryBuffer::SliceWithCache
```

**q2_s50 prenestoff**

```
  TemplatedValidityMask<unsigned long>::SetInvalid: 22 ms
        22 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  VectorBuffer::Copy: 16 ms
        16 ms  리스트 조립/list/struct reader  < VectorStructBuffer::CopyInternal < VectorBuffer::Copy < VectorBuffer::Append
  VectorStringBuffer::CopyInternal: 17 ms
        17 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  ValidityMask::CopySel: 3 ms
         3 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  SelectionVector::Slice: 3 ms
         3 ms  원소 다루기/FILTER  < DictionaryBuffer::SliceInternal < VectorBuffer::Slice < Vector::Slice
```

**q2_s50 prenest**

```
  VectorBuffer::Copy: 3 ms
         3 ms  리스트 조립/list/struct reader  < VectorStructBuffer::CopyInternal < VectorBuffer::Copy < VectorBuffer::Append
  TemplatedValidityMask<unsigned long>::SetInvalid: 11 ms
        11 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  VectorStringBuffer::CopyInternal: 7 ms
         7 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  SelectionVector::Slice: 2 ms
         2 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
  ValidityMask::CopySel: 1 ms
         1 ms  리스트 조립/list/struct reader  < VectorBuffer::Copy < VectorStructBuffer::CopyInternal < VectorBuffer::Copy
```

**q2_s50 pureflat**

```
  VectorBuffer::Copy: 1 ms
         1 ms  값 디코드/decode  < VectorOperations::Copy < DictionaryDecoder::Read < ColumnReader::ReadData
  SelectionVector::Slice: 1 ms
         1 ms  값 디코드/scan  < DictionaryBuffer::SliceInternal < VectorBuffer::Slice < DictionaryBuffer::SliceWithCache
  ValidityMask::CopySel: 1 ms
         1 ms  값 디코드/decode  < StandardVectorBuffer::FlattenSliceInternal < VectorBuffer::FlattenSlice < DictionaryBuffer::Flatten
```

