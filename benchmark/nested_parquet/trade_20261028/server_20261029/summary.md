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
| q2_s01 → s100 | 20~22 | 1.4 | 3.66 → 1.29 | 3.6 → 3.3 | 6.7 → 7.1 | 2.57 → 0.91 |
| q2_m01 → m100 | 23 | 1.35 | 1.35 (미발동) | 2.2 | 2.9~3.1 | 1.00 |
| q2_c01 → c100 | 21~26 | 1.25 | 3.34 → 1.19 | 2.3~2.7 | 5.5~7.4 | 2.61 → 0.94 |
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
  - q2_s100과 q2_c100은 row group 통계로 조건이 항상 참이라, base·flat·pure flat이 평가를 건너뜁니다.
  - q7_plots에서 flat·pure flat의 hash join 40초와 집계 30초(base는 각각 9.5초)는 실행 계획을 아직 확인하지 않았습니다.
