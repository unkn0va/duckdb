# 인수인계: trade fact 중첩 처리 vs join 처리 (2026-10-30 기준)

새 세션은 이 파일부터 읽습니다. 자세한 절차는 `README.md`, 서버 결과와 분석은 `server_20261029/summary.md`에 있습니다.

## 0. 작업 규칙 (사용자 지시)

- **엔진 코드(`src/`, `extension/`)는 고치지 않습니다.** 조사와 추정만 합니다. 코드를 바꾸라는 지시가 따로 있을 때만 바꿉니다.
- 산출물은 이 폴더(`benchmark/nested_parquet/trade_20261028/`) 아래에 둡니다. 실행한 명령은 전부 스크립트로 남겨, 다시 돌릴 수 있게 합니다.
- 보고는 한국어로, 숫자 표와 함께 짧게 합니다. 단계가 끝나면 멈추고 보고한 뒤 지시를 기다립니다.
- 개발과 시험은 이 PC에서, 최종 측정은 apache10에서 합니다(7절).
- 커밋은 목적별로 나눕니다. 저장소 `github.com/unkn0va/duckdb`는 **공개 저장소**이고, 브랜치는 `main_rey`입니다.
- `~/prenest_wt`(브랜치 prenest-3way)는 측정에 쓰지 않습니다.

## 1. 바이너리

다섯 구성은 세 바이너리로 돌립니다.

| 구성 | 바이너리 | 설정 | 쿼리 파일 |
|---|---|---|---|
| base | duckdb_base | 없음 | `queries/*.builtin.sql` (UNNEST) |
| prenestoff | duckdb_prenest_base | `SET parquet_prenest_auto = false;` | builtin |
| prenest | duckdb_prenest_base | `SET parquet_prenest_auto = true;` | builtin |
| flat | duckdb_rey | (run_bench.py의 flat 설정) | `*.flat.sql` (`read_parquet_flat`) |
| pure flat | duckdb_base | 없음 | `*.split.sql` (미리 나눈 파일을 일반 join) |

| 바이너리 | 이 PC (WSL, i5-14500, 16GB) | apache10 (Xeon Gold 5215, 40스레드, 125GiB) |
|---|---|---|
| base | `~/nested-bench/duckdb_base/build/release/duckdb`, `a809d3cd519` (detached worktree) | 같은 경로, `a809d3cd51` |
| prenest | `~/nested-bench/duckdb_prenest_base/build/release/duckdb`, `fabde05fe61` (prenest-3way-base, a809d3cd51 위로 옮긴 것) | 같은 경로, `fabde05fe6` |
| main_rey | `~/nested-bench/duckdb_rey/build/release/duckdb`, `2d345279c39` | 같은 경로, 빌드 `2d6066fd4d`. 저장소는 그 뒤로 pull해 스크립트만 새로 받음 |

- 두 main_rey 빌드의 차이는 `benchmark/`뿐이라서, 다시 빌드할 필요가 없습니다.
- 확인 명령: `README.md` 1절의 `pragma_version()` 루프입니다.
- 이 PC의 작업 저장소는 `~/duckdb_research`(main_rey)이고, 위 세 개는 그 worktree입니다.
- Python: `~/nested-bench/venv/bin/python`(pyarrow 26.0.0, numpy 없음). 두 곳 모두 같습니다.

## 2. 데이터

모든 파일은 `prepare_trade.sh`가 만듭니다. 조건은 고정 시드 20261028 해시 셔플, base 바이너리, pyarrow 26.0.0입니다. 그래서 같은 입력이면 바이트 단위로 같은 파일이 나옵니다(`analysis_20261030/reproducibility/`).

공통 설정:
- row group 122,880행, snappy, v1 page, dictionary 켜짐, page index 없음
- pyarrow 기본 page 크기 1MiB, max_rows_per_page 20000

| 이름 | 위치 | 크기 | 용도 |
|---|---|---|---|
| 1억 행 (`full/`) | **apache10에만** `~/nested-bench/duckdb_rey/benchmark/nested_parquet/trade_20261028/data/full` | 100,000,000행, 약 23GB | 본 측정(bench, explain, profile, check, selectivity) |
| 25만 행 (`distinct/`) | 이 PC `data/distinct` (서버에도 있음) | 서로 다른 249,728행 | 쿼리와 스크립트 시험, 결과 일치 확인, `--data data/distinct`로 run_trade.sh 시험 |
| 2백만 행 샘플 | 이 PC scratchpad(`/tmp`, **지워질 수 있음**). 다시 만드는 법은 아래 | 2,000,000행 (서로 다른 224,830행) | 1억 행과 같은 생성 경로의 작은 판. 행 복제가 있어서 실행 계획 추정과 실제 비교(q7_plots)에 씀 |
| 차원 테이블 (`dims/`) | `data/dims` | csa_dictionary 4행, date_plots 3행, date_plots_flat 10행 | q7 |

각 폴더(`full/`, `distinct/`)의 파일:

| 파일 | 형태 | 쓰는 구성 |
|---|---|---|
| `trade_A.parquet` | c0..c22. c11..c18이 각각 독립 리스트 | q4 (형제 리스트) |
| `trade_B.parquet` | `legs LIST<STRUCT<leg_id, currency, option_type, value>>`(c15..c18), c11..c14는 기본형 리스트 | 대부분의 builtin과 flat |
| `trade_C.parquet` | B에서 c11..c13을 `LIST<STRUCT<v BIGINT>>`로 감쌈 | q3w (prenest는 STRUCT 원소만 받음) |
| `pureflat/parent.parquet` | `sk`와 스칼라 열 | pure flat |
| `pureflat/{c11..c14,legs}.parquet` | `ak0`(부모 sk) + 원소 한 행씩 | pure flat |

1억 행 기준 원소 수와 row group 수:

| 열 | 원소 | 리스트당 최대 | row group |
|---|---|---|---|
| A / B / C / parent | (1억 행) | | 814 |
| c11 | 667,290,000 | 47 | 5431 |
| c12 | 279,810,000 | 4 | 2278 |
| c13 | 192,360,000 | 4 | 1566 |
| c14 | 249,970,000 | 4 | 2035 |
| legs | 349,900,000 | 5 | 2848 |

- legs.value는 c9와 상관계수 0.99999입니다. 그래서 q2_s는 사실상 행 조건입니다.
- 원본
  - 이 PC: `~/Data3/tradeFactTable-001/factTableFormatted.csv`, `/mnt/c/Users/CHOILY/Downloads/{tradeFactTable-001.zip, Data-20261013T061803Z-1-002.zip}`
  - 서버: `~/nested-bench/trade/` (체크섬은 README 1절)
  - Data3와 Umbra는 형식만 다르고 내용은 같습니다. Snowflake는 서로 다른 행은 같고 중복 횟수가 다릅니다.
- 2백만 행 샘플을 다시 만드는 법 (약 1분, 디스크 약 1.5GB). 기록은 `analysis_20261030/sample_2M_prepare.log`에 있습니다.
  ```bash
  S=<임시 폴더>; head -n 2000000 ~/Data3/tradeFactTable-001/factTableFormatted.csv > $S/sample.csv
  cd ~/duckdb_research/benchmark/nested_parquet/trade_20261028
  KEEP_WORK=1 ./prepare_trade.sh $S/sample.csv /mnt/c/Users/CHOILY/Downloads/Data-20261013T061803Z-1-002.zip --out $S/sample_out
  ```

## 3. 스크립트

이 폴더:

| 파일 | 역할 |
|---|---|
| `prepare_trade.sh` | zip(또는 CSV) → 서로 다른 행, 셔플 순서 → A/B/C/pure flat/dims 쓰기 → 검증. `--out`, `--distinct-only`, `KEEP_WORK=1` |
| `write_trade.py` | A/B/C/flat 형식 하나를 씀 (RowGroupWriter로 정확히 122,880행) |
| `verify_trade.sh` | CSV와 각 파일의 원소 수와 내용 일치, row group과 page 수 → `verify.txt` |
| `page_counts.py` | page header를 직접 읽어 열별 page 수를 셈 |
| `make_queries.py` | 40개 쿼리 × 3변형(builtin/flat/split)을 `queries/`에 만듦. 상수를 바꾸면 다시 실행 |
| `check_queries.py` | 다섯 구성의 결과 일치, prenest 카운터(`parquet_prenest_stat`), 계획의 join (`CONFIGS`가 구성 정의) |
| `selectivity.py` | 쿼리별 통과 행 / 원소 비율 |
| `operator_times.py` | 1스레드 EXPLAIN ANALYZE의 연산자 종류별 시간 |
| `summarize_trade.py` | `bench.csv` → `query_times.csv` (구성별 시간, CPU, 비율) |
| `recheck_results.py` | recheck 단계의 결과 요약 |
| `run_trade.sh` | 전체 실행. 단계는 `info check selectivity bench explain`(기본), `profile`, `recheck`(따로 지정)이고, 표는 README 3절에 있음. 변수는 `BASE PRENEST FINAL PY PERF PROFILE_QUERIES ORIG_DATA RUNS(10) THREADS(1,20) QUERY_TIMEOUT(7200) ALLOW_BUSY` |
| `analysis_20261030/q7_variants.sh` | q7_plots 원래 / join 순서 고정 / 집계를 앞으로, 시간과 결과 해시. `PLANS=1`이면 실행 계획 트리(`plan_tree.py`) |
| `analysis_20261030/csv_profile.sql` | 원본 CSV 프로파일 매크로 (첫 단계 데이터셋 조사) |

상위 폴더(`benchmark/nested_parquet/`):

| 파일 | 역할 |
|---|---|
| `run_bench.py` | 구성을 번갈아 실행하고, RUNS 중 최소 시간과 CPU 시간을 잼. 다른 프로세스가 CPU를 쓰면 시작을 거부함(`ALLOW_BUSY=1`로 무시). 결과 비교: 행 전체를 받아 정렬한 뒤 정수·문자열은 정확히, 실수는 상대 1e-9로 비교. `<변형>_<구성>_same` 열을 기록 |
| `profile_breakdown.py` | perf record와 함수 이름으로 범주(pre-nest filter / list assembly / unnest / decode / hash join / aggregate / expressions / vectors / ...)를 나눔. `PERF`, `SETUP`, `CSV_OUT`, `LABEL` 사용 |
| `summarize.py`, `check_results.py` | 이전 측정(followup 등)의 표와 결과 검사. `_same` 열이 있으면 그것을, 없으면 옛 `_result`를 비교 |

## 4. 결과 위치와 주요 결론

- 서버 결과(커밋됨): `server_20261029/`
  - `bench.csv`, `query_times.csv`: 40개 쿼리 × 5개 구성 × {1, 20}스레드
  - `operators_t1.csv`, `check_queries.md`, `selectivity.md`, `profile/`, `recheck/`, `logs/`
  - **`summary.md`에 결과표와 추가 분석이 있습니다.**
- 서버 쪽 원래 폴더: `.../trade_20261028/server_trade/`. 재부팅으로 끊긴 첫 bench는 `server_trade/before_reboot/`에만 있습니다.
- 분석 보조 파일: `analysis_20261030/` (q7 변형 SQL, plan_tree.py, 재현성 해시, 샘플 생성 로그)

주요 결론 (1스레드, base 대비 배수):
- **원소만 쓰는 쿼리(q2, q3, q6_count)는 pure flat이 이깁니다(2.3~7.4배).** flat은 1.2~3.6배, prenest는 1.0~3.7배입니다.
- **부모 열이 필요한 q1은 통과 행 10%와 50% 사이에서 승자가 바뀝니다.** 그 아래에서는 flat·pure flat, 그 위에서는 nested가 이깁니다. 20스레드에서는 q1_s01부터 prenest가 이깁니다.
- prenest 필터의 손익분기점은 통과 원소 75~90%입니다(prenestoff / prenest: q2_c 2.61 → 0.94, q2_s 2.57 → 0.91).
- OR 항이 늘면 prenest가 불리해집니다. q2_or1 → or4에서 prenestoff / prenest는 1.61 → 0.69입니다. 리더 안 평가(OR일 때 원소당 약 41ns, 단일 비교는 약 4.5ns)에 위쪽 FILTER 중복이 더해지기 때문입니다.
- base → prenestoff의 1.3~1.6배는 legs를 쓰는 쿼리에서만 나옵니다. STRUCT 필드 가지치기 덕분이고, q3는 1.0배입니다.
- q6_group과 q7(부모 열 + 그룹/차원 join)은 nested가 이깁니다. q7_plots에서 flat과 pure flat은 0.42배입니다.
- q7_plots의 원인은 **주로 집계 위치이고, 옵티마이저의 순서 선택이 그다음입니다.** 2백만 행 샘플에서 확인했습니다.
  - flat·pure flat은 parent ⋈ dim(실제 3.83배로 불어남, 추정은 1배)을 build로 둡니다. 그리고 불어난 행을 문자열 키로 집계합니다.
  - 순서만 고치면 −12%, 집계를 dim join 앞으로 옮기면 −61%로 base보다 빨라집니다.
- q2_c50에서 flat이 prenestoff보다 2배 빠른 것은 조건 위치 때문입니다.
  - flat은 조건을 스캔 필터로 평가합니다.
  - prenestoff는 UNNEST 뒤 FILTER에서 원소마다 문자열로 비교합니다.
  - perf로 보면 차이는 UNNEST 뒤 "식·벡터" 범주(6.9초 대 0.4초)에서 나옵니다. 중첩을 푸는 비용(조립 1.8초 대 키 생성 3.4초)이 아닙니다.
- 시간 분해 표(6개 쿼리 × 5개 구성, 범주별 %)는 `summary.md`의 "시간 분해"에 있습니다.

## 5. 확인된 사실과 정정된 내용

| 항목 | 내용 |
|---|---|
| 100% 점 (q2_s100, q2_c100, q2_m100) | **통계로 조건을 지우는 것은 pure flat뿐입니다**(q2_s100, q2_c100에서 계획 단계에 사라짐). 처음에는 "base·flat도 통계로 건너뜀"이라고 했는데 틀렸습니다. flat은 스캔 필터로 남고, base·prenestoff는 FILTER에서 원소마다 평가합니다. q2_m100은 모든 구성이 평가합니다. summary.md 표에서 † 표시를 하고 곡선과 따로 다룹니다 |
| prenest와 통계 | prenest의 리스트 리더(`extension/parquet/reader/list_column_reader.cpp:269`)는 배치마다 평가하고 통계를 보지 않습니다. 스칼라 리더(`column_reader.cpp:308`)는 "항상 거짓"만 건너뜁니다. "항상 참"을 건너뛰면 q2_c100의 손해(0.94배)가 약 1.0배가 될 것으로 추정합니다(리더 평가 1.6초) |
| prenest 발동 범위 | OR 조건도 처리합니다(q2_or, q5_or 발동). 비교, BETWEEN, AND/OR, 상수만 받고, 함수(`%` 등)는 받지 않습니다(q2_m 미발동). STRUCT 원소만 받습니다. **기본형 리스트(q3)에서는 발동하지 않고**, STRUCT로 감싼 q3w에서는 발동하지만 이득이 없습니다(0.92~1.08배) |
| 위쪽 FILTER | 리더가 조건을 평가해도 UNNEST 위 FILTER를 일부러 남깁니다(`src/optimizer/prenest_filter_pushdown.cpp:497`). `PrenestFilter::Apply`(`extension/parquet/prenest_filter.cpp:255-279`)는 예외나 필드 불일치가 나면 스스로 꺼지고 모든 원소를 통과시키는데, 그때를 위한 안전망입니다 |
| 위쪽 FILTER를 지운다면 (조사만 함) | 위치: `Absorbed()` 안, `TrySetPrenestFilter` 성공 직후(약 855행). 먼저 할 일: `Apply`의 "모두 통과" 대비책을 오류로 바꾸기, 여러 파일일 때 모든 리더가 받아들였는지 확인하기. 지웠을 때 추정 (prenestoff / prenest): q2_c50 1.37 → 1.54, q2_or2 0.94 → 1.27, q2_or4 0.69 → 1.08 |
| 결과 검사 | `run_bench.py`는 원래 첫 번째 열만 비교했습니다(커밋 ff891acd2dd에서 모든 열로 고침). 그 뒤 반올림한 해시 비교가 TPC-H q01 flat 두 건(상대 2~4e-14 차이)에서 거짓 실패를 냈습니다. **지금은 정수·문자열은 정확히, 실수만 상대 1e-9로 비교합니다**(4b5b4c37892) |
| read_parquet_flat의 행 수 | 결과 행 수가 쓰는 열에 따라 바뀝니다. 리스트 열을 버리면 최상위 행을 셉니다(README "알려진 차이") |
| 결과 일치 | 서버 bench 80행 모두 일치했습니다. check_queries에도 불일치가 없습니다 |

## 6. 아직 설명 못 한 것 / 남은 일

- (이 PC에서 찾음, 서버 확인 대기) **prenestoff 문자열 복사 1.2초와 `SetInvalid` 2.2초**(q2_s50)는 UNNEST 뒤가 아니라 리스트 리더 안에서 생깁니다.
  - 가지치기된 STRUCT 필드는 `StructColumnReader::Read`가 `ConstantVector::SetNull`로 채웁니다(`extension/parquet/reader/struct_column_reader.cpp:88`).
  - `ListColumnReader::ReadInternal` → `VectorBuffer::Append` → `VectorStructBuffer::CopyInternal`이 이 NULL을 리스트 자식에 행마다 복사합니다. 문자열 필드 세 개(leg_id, currency, option_type)의 복사입니다.
  - call stack으로 확인했습니다(`issues_20261030/local_2m/issue1/summary.md` 1-4 끝).
- flat의 100% 점: 스캔 필터가 실행 중에 통계로 건너뛰어지는지 확인하지 못했습니다.
- q3w: prenest가 발동하는데도 이득이 없는 이유를 분해하지 않았습니다.
- OR 조건의 리더 평가가 단일 비교보다 약 9배 비싼 이유(`Apply` 내부)를 분석하지 않았습니다.
- base → prenestoff 1.3~1.6배를 "쓰지 않는 legs 필드의 디코드와 복사가 줄어든 효과"로 본 것은 perf에서 추정한 것입니다.
- q7_plots의 순서 고정·집계 이동 시간은 2백만 행 샘플에서만 쟀습니다. 1억 행 서버에서는 재지 않았습니다(`analysis_20261030/q7_variants.sh <data/full>`로 가능).
- 20스레드 결과는 표에만 있고 분석하지 않았습니다.
- (끝남) 실수 오차 비교로 고친 뒤 서버 recheck를 다시 돌렸습니다. 2026-10-30 `231 checks, 0 failed`가 나왔고, q01 두 건도 통과했습니다.
  결과는 서버의 `trade_20261028/server_recheck_tol/`에만 있습니다.

## 6-1. 2026-10-30 주 이슈 (진행 중)

- 이슈 1(Unnest 오버헤드 분해)과 이슈 2(join 예상 오류)의 스크립트는 `issues_20261030/`에 있습니다(README.md). 이 PC 시험 결과는 `issues_20261030/local_2m/`입니다.
- 서버 결과(2026-10-30): `issues_20261030/server_20261030/`. 정리는 `analysis.md`입니다.
  - 이슈 1과 이슈 2의 cardinality는 끝났습니다.
  - 2-1 variants도 2026-10-31에 다시 돌려 끝났습니다(`issue2/variants.csv`, 60개 결과 일치).
  - 2-1 결론: 예상 오류가 시간을 크게 바꾼 것은 q7_plots뿐입니다(순서 고정 −17%, 합계 먼저 −61%). 같은 변형을 nested에도 적용하면 flat / nested는 2.7배 → 2.2배입니다.
- 주요 결론: 조립은 주로 원소당이고 행 조건과 상관없이 파일의 모든 리스트에서 일어납니다. UNNEST는 리스트당입니다. 문자열 복사 1.2초와 `SetInvalid` 2.2초는 가지치기된 필드의 NULL 복사입니다.
  B의 자식 노드 예상은 num_values와 같고, A의 UNNEST는 리스트 길이를 1로 봅니다.
- perf 범주는 이제 call stack 기준입니다(`categories.py`). 잎 함수만 보던 `profile_breakdown.py`와 숫자가 다르고, 특히 "식·벡터"의 많은 부분이 리스트 조립으로 갑니다.
  사용자 지시: 서버 결과를 정리할 때 **옛 기준과 새 기준을 모두** 보이고, q2_s50 prenestoff의 옛 "식·벡터 6.9초"가 새 기준에서 어디로 가는지 표로 보입니다(`summarize_issue1.py`가 자동으로 만듦).
- 서버 1단계 시험(25만 행, 2026-10-30)은 통과했습니다(stage_check 20 ok, 결과 일치 20/60, 스택 중앙값 35프레임, 3프레임 미만 8%).
- 2-2에서 확인한 것(2백만 행, 합성 TPC-H):
  - flat 자식 노드 스캔의 예상 = 첫 leaf의 `num_values` 합입니다. 빈·NULL 리스트의 자리도 셉니다.
  - UNNEST는 예상이 입력과 같습니다(리스트 길이를 1로 봄).

## 7. 서버(apache10) 실행 규칙

- **서버에는 에이전트가 없습니다.** 사용자가 명령을 손으로 실행하고, 출력이나 스크린샷을 붙여 줍니다.
- 실행 안내는 파일로 만들거나 push하지 않고 **답변으로** 줍니다. 단계는 **반드시 하나씩 차례로** 안내하고, 각 단계의 기대 출력과 예상 시간(추정이면 추정이라고 표시)을 함께 적습니다.
- perf: `perf_event_paranoid = 4`이고 sudo에는 비밀번호가 필요 없습니다. 그래서 `PERF="sudo perf"`를 씁니다(perf 6.8.12).
  - 예: `PERF="sudo perf" ./run_trade.sh --steps profile --out <폴더>`
- 오래 걸리는 단계는 tmux 안에서 돌립니다(`tmux new -s trade`).
- 다른 사용자의 빌드(rustc 등)로 CPU가 바쁘면, run_bench.py가 시작하지 않고 `bench.log`에 이유를 남깁니다.
  - 시간을 재는 단계라면 기다렸다가 다시 돌립니다.
  - 결과만 보는 단계(recheck)는 `ALLOW_BUSY=1`로 돌립니다.
- 커널 업데이트로 재부팅된 적이 있습니다(2026-10-28 17:06). 긴 측정 전후에 `uptime`을 확인합니다.
- `git pull`이 추적하지 않는 파일 때문에 멈추면, 그 파일을 `~/nested-bench/server_backup_20261028/`처럼 옮긴 뒤 다시 pull합니다.
- 결과는 사용자가 scp로 이 PC에 옮깁니다. 그 뒤 `trade_20261028/server_<날짜>/`로 커밋합니다.
- 서버 데이터 경로
  - 1억 행: `trade_20261028/data/full`
  - recheck용 이전 데이터: `~/nested-bench/data`, `~/nested-bench/data_rg1`, `~/nested-bench/data_rg20` (`ORIG_DATA`)

## 8. 커밋 기록 (main_rey)

| 커밋 | 내용 |
|---|---|
| `ff891acd2dd` | run_bench.py: 모든 열로 결과 비교 |
| `24db866bbfe` | trade 실험 스크립트와 쿼리 첫 커밋 (profile_breakdown.py의 PERF/SETUP 변수, pre-nest filter / list assembly / unnest 범주 포함) |
| `ddfd8abe5cf` | q2_c 추가 (행과 상관없는 원소 선택도) |
| `bed7ded9056` | q2_c를 leg_id 단일 비교로, OR 항은 q2_or로. 서버 측정에 쓴 스크립트 상태 |
| `fd0a79a41fa` | 서버 결과 `server_20261029/` |
| `4b5b4c37892` | 결과 검사: 정수·문자열 정확히, 실수 상대 1e-9 |
| `897d206f230` | summary.md 추가 분석 (q7_plots, q2_c50, 위쪽 FILTER, 100% 점, 시간 분해) |
| `ce0a04ed146` | HANDOFF.md, `analysis_20261030/` (scratchpad에 있던 q7 변형 SQL, plan_tree.py, CSV 프로파일 매크로, 재현성 해시, 샘플 생성 로그) |
| `69bd3cab48b` | 서버 recheck 통과 기록 |
| `98502034e46` | 이슈 1·2 스크립트와 쿼리 (`issues_20261030/`) |
| `b8320bc78aa` | 이슈 1·2 이 PC 시험 결과 (`issues_20261030/local_2m/`) |
| (이 커밋) | HANDOFF.md 6, 6-1절 |
