# apache10 측정 결과 (2026-10-28 ~ 29)

`../README.md`의 절차로 apache10(Xeon Gold 5215, 40 스레드, 125 GiB)에서 돌린 결과입니다.
바이너리: base `a809d3cd51`, prenest `fabde05fe6`, main_rey `2d6066fd4d`. 스크립트: `bed7ded9056`.

## 파일

| 파일 | 내용 |
|---|---|
| `verify.txt` | `prepare_trade.sh`의 검증: CSV / A / B / C / pure flat 원소 수와 내용 일치, 파일별 row group과 page |
| `run_info.txt` | 본 측정(bench, explain)의 호스트와 바이너리 |
| `check_queries.md` | 40개 쿼리: 다섯 구성의 결과 일치, prenest 카운터, 실행 계획의 join |
| `selectivity.md` | 쿼리별 통과 행 / 원소 비율 |
| `bench.csv`, `bench.log`, `query_times.csv` | 40개 쿼리 × 5개 구성 × {1, 20} 스레드, 10회 중 최소, CPU 시간 |
| `operators_t1.csv` | 1스레드 EXPLAIN ANALYZE, 연산자 종류별 시간 |
| `profile/`, `profile_test/` | perf(`sudo perf`), 1스레드: 6개 쿼리 × 5개 구성 (1억 행) / q2_s50 (25만 행) |
| `recheck/` | `followup_20261027_0127`의 쿼리 세트를 모든 열 비교로 재검사 |
| `logs/` | `prepare.log`, `run_trade.log`, `recheck.log`, `profile.log`, `profile_test.log` |

## 실행 경과

- check와 selectivity는 2026-10-28 09:15~09:21(UTC)에 끝났습니다.
- bench는 그날 09:21에 시작했지만, 34개 쿼리(q4_one까지)가 끝난 뒤 17:06 서버 재부팅(커널 업데이트)으로 끊겼습니다.
  그 기록은 서버의 `server_trade/before_reboot/`에만 있고 여기에는 넣지 않았습니다.
- 2026-10-29 05:17에 info, bench, explain을 처음부터 다시 돌렸습니다. bench 10시간 18분, explain 58분이 걸렸습니다.
  `logs/run_trade.log`는 이 재실행의 로그입니다.
- 첫 recheck는 다른 사용자의 빌드로 CPU가 바빠 rg 쪽 5개가 시작하지 않았습니다. `ALLOW_BUSY=1`로 다시 돌린 결과가 `recheck/`입니다.
  시간은 재지 않고 결과만 비교하는 단계입니다.

## 확인

- 결과 일치: `query_times.csv` 80행 모두 `yes`, `check_queries.md`에 불일치 없음, `bench.log`에 WARNING 없음.
- recheck: 231개 검사 중 2개 실패(orig, rg1의 TPC-H SF1 q01 flat). sum_disc_price와 sum_charge가 상대 2~4e-14 다르고,
  결과 해시의 반올림(소수 둘째 자리 → 유효숫자 12자리) 경계에 걸린 경우입니다. 개수와 그룹은 같습니다.

## 결과 요약 (1스레드, base 시간 / 각 구성 시간, > 1이면 base보다 빠름)

| 쿼리 | base 초 | prenestoff | prenest | flat | pure flat | prenestoff / prenest |
|---|---|---|---|---|---|---|
| q1_s01 / s10 | 17.0 / 17.4 | 1.53 / 1.55 | 1.52 / 1.54 | 1.44 / 1.32 | 1.55 / 1.57 | 1.00 |
| q1_s50 / s90 / s100 | 18.8 / 20.3 / 19.6 | 1.45 / 1.42 / 1.42 | 1.45 / 1.40 / 1.44 | 0.90 / 0.74 / 0.68 | 0.92 / 0.75 / 0.76 | 1.00 |
| q2_s01 → s100 † | 20~22 | 1.4 | 3.66 → 1.29 | 3.6 → 3.3 | 6.7 → 7.1 | 2.57 → 0.91 |
| q2_m01 → m100 † | 23 | 1.35 | 1.35 (미발동) | 2.2 | 2.9~3.1 | 1.00 |
| q2_c01 → c100 † | 21~26 | 1.25 | 3.34 → 1.19 | 2.3~2.7 | 5.5~7.4 | 2.61 → 0.94 |
| q2_or1 → or4 | 22 → 37 | 1.29 → 1.15 | 2.09 → 0.79 | 2.7 → 2.0 | 5.9 → 2.3 | 1.61 → 0.69 |
| q3_c13 / c12 / c11 | 5.8 / 6.9 / 13.7 | 1.0 | 1.0 | 1.59 / 1.39 / 1.15 | 5.1 / 3.2 / 2.3 | 1.00 |
| q3w_c13 / c12 / c11 | 6.2 / 7.5 / 14.9 | 1.0 | 0.96 / 1.00 / 1.10 | 1.7 / 1.5 / 1.25 | 5.6 / 3.5 / 2.7 | 0.92~1.08 |
| q4_one / q4_two | 12.7 / 109.4 | 1.0 | 1.0 | 1.17 / 1.39 | 2.60 / 1.40 | 1.00 |
| q5_or | 29.1 | 1.06 | 1.08 | 2.16 | 2.89 | 1.02 |
| q6_count / q6_group | 20.9 / 22.3 | 1.44 / 1.36 | 1.83 / 1.75 | 3.59 / 0.89 | 6.96 / 0.87 | 1.27 / 1.29 |
| q7_csa / q7_plots | 11.0 / 39.4 | 1.63 / 1.16 | 1.65 / 1.18 | 1.01 / 0.43 | 1.41 / 0.42 | 1.01 |

- 원소만 쓰는 쿼리는 pure flat이 이깁니다(2.3~7.4배).
- 부모 열이 필요한 q1은 통과 행 10%와 50% 사이에서 승자가 바뀝니다(flat·pure flat 우세 → nested 우세).
  20스레드에서는 q1_s01부터 prenest가 이깁니다.
- prenest 필터의 손익분기점은 통과 원소 75~90%입니다. OR 항이 2개 이상이면 prenest가 prenestoff보다 느립니다.
  리더 안의 평가가 추가되고, 위쪽 FILTER도 그대로 남기 때문입니다.
- base 대비 prenestoff의 1.3~1.6배는 legs를 쓰는 쿼리에서만 나옵니다(q3는 1.0배).
  perf로는 쓰지 않는 legs 필드의 디코드와 복사가 줄어든 효과로 보입니다.
- perf(q1_s50, legs 3.5억 원소): nested의 리스트 조립 + UNNEST는 약 4.4초, flat의 키 생성은 3.4~4.4초입니다.
  부모 열이 필요할 때의 hash join은 8.5~8.9초입니다.
- 주의할 점
  - † 100% 점(q2_s100, q2_c100, q2_m100)은 곡선과 따로, "조건 평가 없음"에 가까운 기준점으로 봅니다.
    구성마다 조건을 다루는 방식이 다릅니다(아래 "100% 점").
  - q7_plots에서 flat·pure flat의 hash join 40초와 집계 30초(base는 각각 9.5초)는 실행 계획을 아직 확인하지 않았습니다.

## 추가 분석 (2026-10-30)

엔진 코드는 바꾸지 않았습니다. 실행 계획은 이 PC의 2백만 행 샘플(같은 생성 경로)과 25만 행 버전으로 보았고, 시간 비율과 perf는 위 서버 결과입니다.

### 100% 점

| 쿼리 | base / prenestoff | prenest | flat | pure flat |
|---|---|---|---|---|
| q2_c100 (`leg_id < 'leh'`) | UNNEST 위 FILTER에서 원소마다 평가 | 리더에서 원소마다 평가 + 위 FILTER | 스캔 필터로 남음 (실행 중 건너뛰는지는 미확인) | **계획에서 조건이 지워짐** |
| q2_s100 (`value < 2000000`) | 같음 | 같음 | 같음 | **계획에서 조건이 지워짐** |
| q2_m100 (`value % 100 < 100`) | 평가 | 평가 (prenest 미발동) | 평가 | 평가 |

- 통계로 조건을 지우는 것은 pure flat뿐입니다(최상위 열의 통계로 옵티마이저가 "항상 참"을 증명).
  base의 FILTER 시간이 100%에서 줄어드는 것(q2_c75 5.4초 → q2_c100 1.4초)은 통계 때문이 아니라 모든 원소가 통과해서입니다.
- prenest의 리스트 리더(`reader/list_column_reader.cpp:269`)는 배치마다 조건을 평가하고 통계를 보지 않습니다.
  스칼라 열 리더(`column_reader.cpp:308`)는 `CheckStatistics`로 "항상 거짓"인 row group만 건너뜁니다.
- 추정: prenest가 원소 열의 row group 통계로 "항상 참"을 건너뛴다면, q2_c100의 리더 평가 1.6초(스캔 12.98초 대 prenestoff 11.39초)와
  q2_s100의 1.3초가 사라집니다. 그러면 prenestoff / prenest가 0.94 / 0.91에서 약 1.0이 됩니다.

### q7_plots: flat과 pure flat이 0.42배인 이유

flat과 pure flat은 parent ⋈ dim을 먼저 하고, 그 결과를 build로 둔 뒤 legs로 probe합니다.
옵티마이저는 parent ⋈ dim의 결과를 parent 행 수(2백만)로 추정했지만, 실제로는 3.83배(767만)였습니다. dim은 키 하나에 날짜 1~5행입니다.
base는 UNNEST한 legs로 dim(10행)을 probe합니다.

2백만 행 샘플, 1스레드 (초, 결과는 모두 같음):

| 구성 | 원래 | join 순서 고정 (legs ⋈ parent, 그다음 dim을 build) | 집계를 dim join 앞으로 (c8별로 먼저 집계) |
|---|---|---|---|
| base | 0.401 | (원래 이 순서) | 0.234 |
| flat | 0.906 | 0.797 | 0.352 |
| pure flat | 0.914 | 0.818 | 0.402 |

- 서버 perf(1억 행)를 보면 추가 시간은 두 덩어리입니다.
  - 큰 build를 만드는 비용: `InsertHashes`, `GetRowPointers` 약 15초와 kernel 11~13초
  - 불어난 행마다 문자열 그룹 키를 해시하는 비용: `Hash<string_t>` 15초, base는 1.8초
- 결론: 주 원인은 **집계 위치**입니다. dim join으로 3.8배 불어난 행을 문자열 키로 집계합니다.
  옵티마이저의 순서 선택(dim join 결과를 과소추정해 큰 build를 고름)은 그다음입니다.
  순서만 고치면 12% 줄고, 집계를 dim join 앞으로 옮기면 61% 줄어 base보다 빨라집니다.

### q2_c50: flat(2.28배)과 prenestoff(1.22배)의 차이

서버 EXPLAIN ANALYZE (초):

| 구성 | 전체 | 스캔 | UNNEST | FILTER | 집계·기타 |
|---|---|---|---|---|---|
| prenestoff | 21.36 | 11.65 | 2.80 | 5.72 | 0.51 |
| flat | 11.42 | 10.77 | 0 | 0 (스캔 안) | 0.40 |

- **조건이 평가되는 위치가 다릅니다.** flat과 pure flat은 `leg_id < 'leg270'`을 스캔 필터(`Filters:`)로 넣습니다.
  그래서 리더가 열 단위로 비교하고, 통과한 행의 value만 읽습니다.
  prenestoff는 UNNEST 뒤 FILTER에서 `struct_extract(e, 'leg_id')`를 원소마다 문자열로 비교합니다(5.7초).
- 같은 모양인 q2_s50의 perf 범주 (초):

  | 범주 | prenestoff | flat |
  |---|---|---|
  | 값 디코드 | 1.1 | 1.6 (스캔 필터 0.5 포함) |
  | 리스트 조립 / 키 생성 | 1.8 | 3.4 |
  | UNNEST | 2.6 | 0 |
  | expressions + vectors | 6.9 | 0.4 |
  | 집계 | 0.2 | 0.3 |
  | 기타 (libc, kernel 등) | 2.7 | 0.6 |

  - 중첩을 푸는 비용(조립 1.8초 대 키 3.4초)이 아니라, UNNEST 이후 원소를 벡터로 다루는 비용이 차이를 만듭니다.
  - 여기에는 STRUCT 값 꺼내기, validity(`SetInvalid` 2.2초), 복사(`VectorStringBuffer::CopyInternal` 1.2초, `VectorBuffer::Copy`), FILTER 평가가 포함됩니다.
  - prenestoff는 legs의 value만 읽는데도 문자열 복사가 남는 이유는 확인하지 못했습니다.

### prenest의 위쪽 FILTER 중복 평가

서버 EXPLAIN ANALYZE (초). 리더 안 평가는 같은 쿼리의 prenestoff와 비교한 스캔 시간 증가분입니다. 원소를 덜 붙여 아낀 시간이 빠진 순 증가분이라 추정치입니다.

| 쿼리 | prenest 스캔 | prenestoff 스캔 | 리더 평가 (순 증가) | 위쪽 FILTER (prenest / prenestoff) | 위쪽 FILTER를 지우면 (추정) |
|---|---|---|---|---|---|
| q2_c50 | 10.76 | 11.65 | −0.9 (아낀 시간이 더 큼) | 1.68 / 5.72 | 15.6 → 13.9초, off 대비 1.37 → 1.54배 |
| q2_or2 | 17.13 | 11.53 | +5.6 | 7.00 / 10.23 | 27.3 → 20.3초, 0.94 → 1.27배 |
| q2_or4 | 25.87 | 11.54 | +14.3 | 16.99 / 16.99 | 47.2 → 30.2초, 0.69 → 1.08배 |

- 위쪽 FILTER는 일부러 남깁니다(`src/optimizer/prenest_filter_pushdown.cpp:497`, "The binder itself is deliberately NOT removed").
  리더의 `PrenestFilter::Apply`가 평가 중 예외가 나거나 구조체 필드 수가 맞지 않으면, 스스로 꺼지고 모든 원소를 통과시킵니다(`extension/parquet/prenest_filter.cpp:255-279`).
  그때 결과를 지키는 것이 위쪽 FILTER입니다.
- 지운다면 이렇게 해야 합니다.
  - 위치: 리더가 spec을 받아들였다는 것이 확정되는 `Absorbed()` 안, `TrySetPrenestFilter(specs)`가 성공한 직후(`prenest_filter_pushdown.cpp`, 약 855행)입니다. 거기서 그 comprehension을 만든 원래 조건을 위쪽 Filter에서 빼면 됩니다.
  - 조건 1: 그 조건이 예외를 낼 수 없는 종류여야 합니다(`IsPushablePredicate`가 이미 보장).
  - 조건 2: `Apply`의 "모든 원소 통과" 대비책을 오류로 바꿔야 합니다. 그대로 두면 리더가 꺼질 때 결과가 틀립니다.
  - 조건 3: 여러 파일을 읽을 때 모든 파일의 리더가 spec을 받아들였는지 확인해야 합니다.
- OR 쿼리에서는 리더 평가 자체도 비쌉니다(q2_or4는 원소당 약 41ns, 단일 비교인 q2_c100은 약 4.5ns).
  그래서 위쪽 FILTER를 지워도 q2_or4는 prenestoff와 비슷한 수준(1.08배)까지만 회복됩니다(추정).

### 시간 분해 (서버 perf, 1스레드, 범주별 CPU 비율 %)

- 디코드 = parquet decode + levels/skip
- FILTER = 스캔 필터 + pre-nest filter
- 식·벡터 = expressions + vectors. UNNEST 위 FILTER의 평가도 여기에 들어갑니다.
- 기타 = libc, kernel, hashing 등

| 쿼리 | 구성 | CPU 초 | 디코드 | 조립 | 키 | FILTER | UNNEST | join | 집계 | 식·벡터 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| q1_s50 | base | 19.5 | 17 | 11 | · | · | 7 | · | 1 | 42 | 22 |
| q1_s50 | prenestoff | 13.6 | 9 | 13 | · | · | 9 | · | 2 | 44 | 22 |
| q1_s50 | prenest | 13.4 | 9 | 14 | · | · | 10 | · | 2 | 44 | 21 |
| q1_s50 | flat | 21.6 | 6 | · | 21 | 1 | · | 43 | 9 | 8 | 13 |
| q1_s50 | pure flat | 22.4 | 18 | · | · | · | · | 40 | 7 | 12 | 23 |
| q2_m50 | base | 23.8 | 13 | 8 | · | · | 11 | · | 1 | 49 | 17 |
| q2_m50 | prenestoff | 17.6 | 6 | 10 | · | · | 15 | · | 1 | 53 | 15 |
| q2_m50 | prenest | 17.6 | 6 | 10 | · | · | 15 | · | 1 | 53 | 15 |
| q2_m50 | flat | 10.7 | 10 | · | 32 | · | · | · | 3 | 49 | 6 |
| q2_m50 | pure flat | 8.4 | 12 | · | · | · | · | · | 4 | 66 | 18 |
| q2_s50 | base | 21.4 | 14 | 10 | · | · | 12 | · | 1 | 43 | 20 |
| q2_s50 | prenestoff | 15.3 | 7 | 12 | · | · | 17 | · | 1 | 45 | 18 |
| q2_s50 | prenest | 12.4 | 9 | 17 | · | 1 | 21 | · | 2 | 35 | 15 |
| q2_s50 | flat | 6.2 | 17 | · | 55 | 9 | · | · | 5 | 6 | 9 |
| q2_s50 | pure flat | 3.9 | 34 | · | · | 5 | · | · | 8 | 15 | 38 |
| q3_c11 | base | 14.0 | 21 | 17 | · | · | 21 | · | 3 | 26 | 12 |
| q3_c11 | prenestoff | 13.9 | 21 | 17 | · | · | 21 | · | 3 | 25 | 12 |
| q3_c11 | prenest | 13.9 | 22 | 17 | · | · | 21 | · | 3 | 25 | 12 |
| q3_c11 | flat | 12.1 | 25 | · | 50 | 8 | · | · | 4 | 6 | 7 |
| q3_c11 | pure flat | 6.4 | 43 | · | · | 3 | · | · | 9 | 14 | 31 |
| q4_two | base | 112.7 | 4 | 4 | · | · | 5 | 28 | 12 | 22 | 26 |
| q4_two | prenestoff | 112.5 | 4 | 4 | · | · | 5 | 28 | 12 | 21 | 26 |
| q4_two | prenest | 113.7 | 4 | 4 | · | · | 5 | 28 | 12 | 21 | 26 |
| q4_two | flat | 80.3 | 5 | · | 12 | · | · | 30 | 15 | 18 | 20 |
| q4_two | pure flat | 80.7 | 9 | · | · | · | · | 31 | 15 | 20 | 26 |
| q7_plots | base | 41.1 | 8 | 5 | · | · | 6 | 16 | 8 | 27 | 29 |
| q7_plots | prenestoff | 34.4 | 3 | 5 | · | · | 7 | 19 | 10 | 26 | 29 |
| q7_plots | prenest | 34.4 | 3 | 5 | · | · | 8 | 19 | 10 | 26 | 29 |
| q7_plots | flat | 94.0 | 1 | · | 5 | · | · | 28 | 20 | 8 | 38 |
| q7_plots | pure flat | 99.7 | 4 | · | · | · | · | 26 | 19 | 9 | 42 |
