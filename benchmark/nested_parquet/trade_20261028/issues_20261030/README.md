# 이슈 1·2 (2026-10-30 주): Unnest 오버헤드 분해, join 예상 오류

엔진 코드는 바꾸지 않았습니다. 이 폴더의 스크립트는 `../data/full`(1억 행)과 `~/nested-bench/` 바이너리를 기본값으로 씁니다. 이 PC에서는 25만 행·2백만 행 샘플과 합성 TPC-H로 시험했습니다(`local_2m/`).

## 파일

| 파일 | 역할 |
|---|---|
| `run_issue1.sh` | 이슈 1. 단계 `info stages params tpch summary`. 결과 폴더에 `stage_check.md`, `stage_time.csv`, `stage_plans/`, `counts.csv`, `profile/{stage,params,tpch_sf1,tpch_sf10}/`, `summary.md` |
| `run_issue2.sh` | 이슈 2. 단계 `info variants cardinality summary`. 결과 폴더에 `variants.csv`, `variant_plans/`, `cardinality.csv`, `summary.md` |
| `make_issue_queries.py` | `queries_stage/`(1-1 단계 쿼리)와 `queries_plans/`(2-1 변형)를 만듦. 상수는 `../make_queries.py`에서 가져옴 |
| `profile_stacks.py` | perf를 call stack(`--call-graph dwarf`)과 함께 돌려 범주별 CPU 시간을 냄. 측정하는 두 번째 실행만 샘플링(perf control fifo + CLI `.shell`) |
| `categories.py` | 범주 규칙(1-4). `table`은 규칙표, `classify <folded.gz>`는 기록된 스택을 다시 나눔 |
| `time_queries.py` | 다섯 구성으로 쿼리 파일을 RUNS번 재고(최소), 결과를 원래 쿼리(base builtin)와 비교. 파일 앞의 `SET`은 시간 밖에서 실행. `SAME_PLAN=1`이면 원래와 계획이 같은 변형은 다시 재지 않음 |
| `stage_check.py` | 단계 쿼리가 의도한 단계에서 멈추는지 실행 계획으로 확인 |
| `counts.py` | 1-2의 리스트 수와 원소 수(base EXPLAIN ANALYZE + 파일) |
| `cardinality.py` | 2-2: join, UNNEST, 그 입력 스캔의 예상·실제 행 수, q-error, join 종류, flat 노드의 `num_values`와 실제 노드 행 수 |
| `plans.py` | EXPLAIN ANALYZE JSON을 연산자 목록과 트리 글로 바꿈 |
| `summarize_issue1.py`, `summarize_issue2.py` | 결과 폴더 → `summary.md` |
| `local_2m/` | 이 PC의 시험 결과. trade는 2백만 행 샘플, TPC-H는 `synthetic_tpch.sql`로 만든 작은 합성 데이터(구조만 같고 값은 실제와 다름) |

## 정의

### 1-1 단계 쿼리 (`queries_stage/`)

| 단계 | builtin (base, prenestoff, prenest) | flat | pure flat |
|---|---|---|---|
| s1_box | `sum(len(legs))` | `count("legs._sk")` (키만) | `count(ak0)` |
| s2_unnest | UNNEST 뒤 `count(*)` | `count("legs.leg_id"), count("legs.value")` | `count(leg_id), count(value)` |
| s2f_fields | UNNEST 뒤 `count(e.leg_id), count(e.value)` | s2와 같음 | s2와 같음 |
| s3_cond | q2_c50 | q2_c50 | q2_c50 |

- prenest 바이너리는 STRUCT 필드를 참조할 때만 가지치기를 합니다. 그래서 s2_unnest는 legs의 네 필드를, s3_cond는 두 필드를 읽습니다. s2f_fields는 그 사이를 잇는 단계입니다.
- pure flat은 통계가 NULL 없음을 보이면 `count(열)`을 메타데이터로 답합니다. 그래서 s1, s2에서는 `statistics_propagation`을 끕니다(파일 앞의 `SET`).

### 2-1 변형 (`queries_plans/`)

- `orig`: `../queries`의 쿼리.
- `fixed`: `join_order`를 끄고, 원소 → 부모 → 차원 표 순서로 씁니다. build 쪽은 `build_side_probe_side`가 정합니다. builtin과 flat은 글이 같고 설정만 다릅니다(builtin의 join은 차원 표 하나뿐이고, flat의 부모⋈자식 join은 `read_parquet_flat` 안에서 만들어짐).
- `preagg`: 차원 표 join 앞에서 집계합니다. q7_csa는 (c0, c1)별, q7_plots는 c8별이고, 다섯 구성 모두에 적용합니다. q1, q6에는 차원 표 join이 없어서 만들지 않았습니다.

### 1-4 범주

`categories.py table`의 규칙을 씁니다. 샘플의 스택을 잎에서 위로 따라가며 처음 맞는 규칙이 범주를 정하고, memcpy·malloc·kernel·validity·벡터 도우미는 부른 쪽의 범주를 받습니다.
이전 `../../profile_breakdown.py`는 잎 함수만 보고 인자 이름까지 맞췄습니다. 그래서 그 표의 "식·벡터"에 들어 있던 것 중 상당 부분이 이 분류에서는 리스트 조립으로 갑니다.

### 2-2 join 종류

| 종류 | 기준 |
|---|---|
| nesting: parent-child | 조건이 모두 키 열이고, 한쪽은 `_sk`/`sk`, 다른 쪽은 `_akN`/`akN` |
| nesting: sibling | 양쪽 모두 `_akN`/`akN`, 또는 builtin q4_two의 행 번호(`rn`) |
| nesting: UNNEST | 방식 A의 UNNEST. 예상은 입력의 예상을 그대로 씀(`src/planner/logical_operator.cpp:261-272`) |
| regular | 그 밖(차원 표 등) |

## 이 PC에서 시험한 방법

perf는 Ubuntu 패키지(`linux-tools-6.8.0-147`, perf 6.8.12, 서버와 같은 판)를 설치하지 않고 풀어서 썼습니다. WSL에는 하드웨어 PMU가 없어 task-clock으로 샘플링했습니다.

```bash
RUNS=3 ALLOW_BUSY=1 ./run_issue1.sh --data <2백만 행 샘플>/full --out <폴더> --steps "info stages params"
RUNS=2 ALLOW_BUSY=1 ORIG_DATA=<합성 TPC-H> ./run_issue1.sh --data <2백만 행 샘플>/full --out <같은 폴더> --steps "tpch summary"
RUNS=2 ALLOW_BUSY=1 CARD_THREADS=8 ORIG_DATA=<합성 TPC-H> ./run_issue2.sh --data <2백만 행 샘플>/full --out <폴더>
```

- 2-2의 행 수는 스레드 수에 따라 바뀌지 않았습니다(2백만 행, 1스레드와 16스레드에서 323행 모두 같음). 그래서 서버에서는 20스레드로 돌립니다.
- 이 PC의 2백만 행 시간을 92배 하면 서버 1억 행 1스레드 시간이 됩니다(중앙값, 12개 쿼리 × 5개 구성).
