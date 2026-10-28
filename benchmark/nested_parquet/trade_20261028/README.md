# trade fact 데이터: 중첩 처리 vs join 처리

이 폴더의 스크립트로 apache10에서 데이터를 만들고 측정합니다. 위에서부터 순서대로 복사해 붙이면 됩니다.
경로는 `../SERVER.md`와 같은 `~/nested-bench/` 구조를 따릅니다.

```
~/nested-bench/
├── duckdb_base/           원래 DuckDB (a809d3cd519)
├── duckdb_prenest_base/   prenest-3way-base (fabde05fe61)
├── duckdb_rey/            main_rey (read_parquet_flat), 이 폴더도 여기 있음
├── venv/                  pyarrow 26.0.0
└── trade/                 원본 zip 두 개
```

## 1. 준비

### Python 환경 (pyarrow 26.0.0)

`../SERVER.md` 1절의 venv(`~/nested-bench/venv`, pyarrow 26.0.0)가 이미 있으면 건너뜁니다. 없으면 아래처럼 만듭니다. 서버에 `python3-venv`(ensurepip)가 없어도 되도록 pip를 직접 받습니다.

```bash
mkdir -p ~/nested-bench && cd ~/nested-bench
python3 -m venv --without-pip venv
curl -sS -o get-pip.py https://bootstrap.pypa.io/get-pip.py
venv/bin/python get-pip.py
venv/bin/pip install pyarrow==26.0.0
venv/bin/python -c "import pyarrow; print('pyarrow', pyarrow.__version__)"
```

마지막 줄이 `pyarrow 26.0.0`이어야 합니다. numpy는 필요 없습니다.

### 바이너리와 스크립트

apache10에는 지난 측정(`../followup_20261027_0127/run_info.txt`)의 세 바이너리가 이미 있습니다. 스크립트만 새로 받습니다.
2d6066fd4d 이후 main_rey의 커밋은 `benchmark/`만 바꾸므로 다시 빌드할 필요는 없습니다.

```bash
cd ~/nested-bench/duckdb_rey && git pull origin main_rey
for b in duckdb_base duckdb_prenest_base duckdb_rey; do
  ~/nested-bench/$b/build/release/duckdb -no-agent -noheader -list -c "SELECT '$b ' || source_id FROM pragma_version()"
done
```

source_id가 각각 `a809d3cd51`, `fabde05fe6`, `2d6066fd4d`(또는 그 뒤 커밋)이면 됩니다.
prenest 바이너리가 없으면 같은 저장소에서 worktree로 꺼내 빌드합니다.

```bash
cd ~/nested-bench/duckdb_rey
git fetch origin prenest-3way-base
git worktree add ~/nested-bench/duckdb_prenest_base fabde05fe61
cd ~/nested-bench/duckdb_prenest_base && CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) GEN=ninja make release
```

### 원본 zip

노트북의 `Downloads`에서 두 파일을 서버의 `~/nested-bench/trade/`로 복사하고 체크섬을 확인합니다.

```bash
cd ~/nested-bench/trade
sha256sum -c - <<'EOF'
d159ac19441c4e9c787076a66e1231a58fea028d6b79aa89fc637cd7c803359f  tradeFactTable-001.zip
e26f2ae1e2290a0f825f02ffc97ae31b4fa9d9c189980bf0fb3deb9e6dda5b1c  Data-20261013T061803Z-1-002.zip
EOF
```

## 2. Parquet 만들기

```bash
cd ~/nested-bench/duckdb_rey/benchmark/nested_parquet/trade_20261028
./prepare_trade.sh ~/nested-bench/trade/tradeFactTable-001.zip ~/nested-bench/trade/Data-20261013T061803Z-1-002.zip \
  2>&1 | tee prepare.log
```

- 결과는 `data/`에 생깁니다. `full/`(1억 행), `distinct/`(서로 다른 249,728행), `dims/`(차원 테이블)입니다.
  검증 결과는 `data/verify.txt`에 저장됩니다.
- 같은 입력이면 바이트 단위로 같은 파일이 나옵니다. 고정 시드 해시로 섞고, base 바이너리와 pyarrow 26.0.0으로 쓰기 때문입니다.
- 중간 파일(`data/work/`, 풀어 놓은 CSV 31GB 포함)은 끝나면 지워집니다. 남기려면 `KEEP_WORK=1`을 주세요.

**예상 자원** (200만 행 샘플에서 늘려 잡은 값):

| 항목 | 값 |
|---|---|
| 시간 | zip 풀기 약 5분, 서로 다른 행 세기 약 5분, 셔플 순서 약 2분, A·B·C·pure flat 쓰기 약 10분(병렬), 검증 약 25분 |
| 디스크 | 최대 약 65GB: 풀어 놓은 CSV 31GB, 결과물 약 23GB, DuckDB 임시 파일 |
| 메모리 | 쓰기 프로세스 4개가 각각 약 1.5GB, DuckDB 단계는 기본 메모리 한도(RAM의 80%) 안에서 넘치면 디스크로 내려 씀 |

### 파일 구성

| 파일 | 내용 |
|---|---|
| `trade_A.parquet` | c0..c22. c11..c18이 각각 독립 리스트 |
| `trade_B.parquet` | c0..c14, `legs LIST<STRUCT<leg_id, currency, option_type, value>>`(c15..c18을 묶음), c19..c22 |
| `trade_C.parquet` | B에서 c11, c12, c13을 `LIST<STRUCT<v BIGINT>>`로 감쌈 (prenest는 STRUCT 원소의 필드 조건만 받음) |
| `pureflat/parent.parquet` | `sk`(B의 행 번호, 0부터)와 스칼라 열 |
| `pureflat/{c11,c12,c13,c14}.parquet` | `ak0`(부모 sk)와 원소, 원소 하나가 한 행 |
| `pureflat/legs.parquet` | `ak0`, leg_id, currency, option_type, value |
| `dims/csa_dictionary.parquet` | csa, as_of_date, csa_hash |
| `dims/date_plots.parquet` / `date_plots_flat.parquet` | reg_scenario와 날짜 리스트 / 날짜 하나가 한 행 |

모든 파일은 pyarrow 26.0.0 기본 설정으로 씁니다(snappy). row group은 정확히 122,880행이고, 마지막 row group만 더 작습니다.

## 3. 측정

`prepare_trade.sh`가 끝나면 `data/verify.txt`부터 확인합니다. `all_sources_agree`가 모두 `true`이고 불일치가 모두 0이어야 합니다.
측정은 몇 시간 걸리므로 tmux 안에서 돌리세요.

```bash
tmux new -s trade
cd ~/nested-bench/duckdb_rey/benchmark/nested_parquet/trade_20261028
./run_trade.sh 2>&1 | tee run_trade.log
```

- 결과는 `server_<날짜_시각>/`에 생깁니다. `--out <폴더>`로 바꿀 수 있습니다.
- 바이너리 경로는 `run_trade.sh` 맨 위 변수(`BASE`, `PRENEST`, `FINAL`)에 있습니다. 기본값은 `~/nested-bench/` 구조이고, 환경 변수로도 바꿀 수 있습니다.
- 기본값은 1스레드와 20스레드에서 각 10회 중 최소입니다(`THREADS=1,20 RUNS=10`).
- 단계별로 나눠 돌릴 수 있습니다. 예: `--steps "bench"`
- 다른 프로세스가 CPU를 쓰고 있으면 `run_bench.py`가 시작하지 않습니다(`bench.log`에 이유가 남음). 그 프로세스가 끝난 뒤 다시 돌리세요.

| 단계 | 결과 파일 | 내용 | 예상 시간 |
|---|---|---|---|
| info | `run_info.txt` | 호스트, CPU, 메모리, 바이너리 버전과 커밋 | 몇 초 |
| check | `check_queries.md` | 다섯 구성의 결과 일치, prenest 카운터(평가/디코드, 추가/디코드 비율 포함), 실행 계획의 join | 약 30분 |
| selectivity | `selectivity.md` | 쿼리마다 통과 행 비율과 통과 원소 비율 | 약 5분 |
| bench | `bench.csv`, `query_times.csv` | 36개 쿼리 × 5개 구성 × {1, 20}스레드, 10회 중 최소, CPU 시간 | 1스레드 약 5시간 + 20스레드 약 50분 |
| explain | `operators_t1.csv` | 1스레드 EXPLAIN ANALYZE, 연산자 종류별 시간 | 약 30분 |
| profile (기본 단계 아님) | `profile/` | perf 샘플링, 1스레드, 6개 쿼리 × 5개 구성 | 약 30분 |
| recheck (기본 단계 아님) | `recheck/summary.md` | 지난 측정의 쿼리 세트를 고친 결과 검사로 다시 확인, 시간 측정 없음 | 약 1시간 |

- 예상 시간은 노트북(i5-14500)에서 25만 행 버전으로 잰 시간을 1억 행으로 선형으로 늘려 잡은 값입니다. 서버에서는 달라질 수 있습니다.
- 가장 오래 걸리는 쿼리는 q4_two(형제 리스트 곱집합, 약 17억 쌍)와 q7_plots입니다.
- 한 쿼리·구성의 10회가 `QUERY_TIMEOUT`(기본 7200초)을 넘으면 그 칸은 오류로 남습니다.
- 메모리: q4_two의 hash join이 c14 원소 약 2.5억 행을 build합니다(수 GB). 서버의 125GiB면 충분합니다.

### profile: 스캔 시간을 값 디코드 / 리스트 조립 / 기타로 나누기

EXPLAIN ANALYZE의 TABLE_SCAN 시간에는 값 디코드와 리스트 조립이 함께 들어 있습니다. 둘을 나누려면 perf 샘플링이 필요합니다.
`../profile_breakdown.py`가 함수 이름으로 범주를 나눕니다.
- 리스트 조립: `ListColumnReader`, `StructColumnReader`
- prenest 필터: `PrenestFilter::Apply`
- 값 디코드: parquet decode, levels/skip, scan filters
- 그 밖에 unnest, hash join, aggregate 등

apache10은 `perf_event_paranoid = 4`라서 일반 사용자는 샘플링할 수 없습니다. 관리자가 설정을 낮추거나 sudo를 허락한 뒤에 돌립니다.

```bash
# 설정을 낮춘 경우
./run_trade.sh --steps profile --out server_<위와 같은 폴더>
# sudo perf를 쓰는 경우: 비밀번호를 미리 입력해 두고 PERF를 바꿈 (perf.data는 실행 사용자 소유로 바뀜)
sudo -v && PERF="sudo perf" ./run_trade.sh --steps profile --out server_<위와 같은 폴더>
```

- 시작 전에 `perf record`를 짧게 시험하고, 안 되면 경고만 출력하고 이 단계를 건너뜁니다.
- 대상 쿼리는 `PROFILE_QUERIES`(기본: q1_s50 q2_m50 q2_s50 q3_c11 q4_two q7_plots)이고, 결과는 다음 위치에 남습니다.
  - `profile/<쿼리>.<구성>.txt`: 범주별 CPU ms, 가장 바쁜 함수, 타임라인
  - `profile/profile.csv`: 모든 실행을 한 표로
  - `profile/*.perf.data`: 원본 샘플
- `nm`(binutils)이 필요합니다.
- sudo로 돌리면 DuckDB도 root로 실행됩니다. 쿼리는 파일을 읽기만 합니다.

### recheck: 지난 결과 다시 검사

`run_bench.py`는 커밋 ff891acd2dd 전까지 결과의 첫 번째 열만 비교했습니다. recheck는 `followup_20261027_0127`의 쿼리 세트 전체를 고친 검사로 한 번씩(1스레드, RUNS=1) 다시 돌려 모든 열이 같은지 봅니다.
- 쿼리 세트: TPC-H SF1·SF10, XMark, DBLP, Selectivity (A)·(B)
- 파일: 원래 파일과 rg1/rg20 재작성 파일
- 구성: base / prenestoff / prenest는 builtin, main_rey는 flat·flat_minmax (selectivity는 지난번과 같은 query 설정)

서버의 기존 데이터 경로를 그대로 씁니다.
- `~/nested-bench/data`: `../SERVER.md` 3~5절의 논문 데이터와 선택도 데이터
- `~/nested-bench/data_rg1`, `~/nested-bench/data_rg20`: `followup_checks.sh --steps rewrite`가 만든 파일

다른 곳에 있으면 `ORIG_DATA=<폴더>`를 주세요. 없는 파일은 건너뛰고 로그에 남깁니다.

```bash
./run_trade.sh --steps recheck --out server_<위와 같은 폴더>
cat server_<폴더>/recheck/summary.md
```

`summary.md`에는 데이터셋마다 검사 수와 실패 수가 있고, 실패한 쿼리·열과 비교 대상이 그 아래 나열됩니다.

### 쿼리

쿼리는 `make_queries.py`가 `queries/`에 만듭니다. 상수를 바꾸면 이 스크립트를 다시 실행하세요.
쿼리마다 세 파일이 있습니다.
- `builtin`: base / prenestoff / prenest가 실행
- `flat`: main_rey의 `read_parquet_flat`
- `split`: pure flat. base로 일반 join

| 쿼리 | 파라미터 | 내용 |
|---|---|---|
| q1_s{01,10,50,90,100} | 최상위 조건 선택도 | `c9 < 임계값`, legs.value 합계 |
| q2_s{01,10,50,90,100} | 원소 조건 선택도, 행과 상관있음 | `legs.value < 임계값`, 합계. value는 trade 번호를 따라가므로(c9와 상관계수 0.99999) 사실상 행 조건 |
| q2_m{01,10,50,90,100} | 원소 조건 선택도, 행과 상관없음 (prenest 미발동) | `legs.value % 100 < k`, 합계. 원소 1%일 때 통과 행 3.5%. base·flat 비교용 |
| q2_c{01,10,25,50,75,100} | 원소 조건 선택도, 행과 상관없음 (prenest 발동) | prenest가 받는 비교·OR만 사용: `leg_id < 'leg103'`(0.9%), `leg_id < 'leg134'`(10.1%), `currency = 'EUR'`(24.6%), EUR OR USD(48.9%), EUR OR USD OR GBP(73.2%), 네 통화 OR(100%). 원소 1%일 때 통과 행 3.3% |
| q2_cat_common / q2_cat_rare | 범주형 원소 조건 | `currency = 'AUD'`(26.8%) / `leg_id = 'leg39'`(0.023%, currency에는 드문 값이 없음) |
| q3_{c13,c12,c11} | 리스트 길이 (legs는 q2_s50) | B 파일에서 펼침 + 원소 약 50% 조건 + 합계 |
| q3w_{c13,c12,c11} | q3의 STRUCT 감싼 버전 | C 파일에서 같은 쿼리 (`e.v`) |
| q4_one / q4_two | 펼치는 리스트 개수 (A 파일) | c11만 / c11 × c14 부모별 곱집합 |
| q5_or | OR 조건 | `currency = 'AUD' OR option_type = 'put'` |
| q6_count / q6_group | 집계 종류 (SUM은 q2_s50) | q2_s50 조건으로 COUNT / c5별 GROUP BY |
| q7_csa / q7_plots | 차원 테이블 조인 | csa_dictionary와 (c0, c1)로 / date_plots_flat과 c8로 |

prenest가 발동하는 쿼리는 q2_s, q2_c, q2_cat, q3w, q5_or, q6입니다. 발동하지 않는 쿼리와 그 이유는 다음과 같습니다.
- q1, q4, q7: 원소 조건이 없음
- q3: 기본형 리스트라서 spec이 만들어지지 않음
- q2_m: `%`는 함수라서 밀어 넣지 않음. prenest는 비교와 BETWEEN만 받음(실행 중 오류를 낼 수 있는 함수는 UNNEST 위에 남김)

## 알려진 차이

### read_parquet_flat의 결과 행 수는 사용하는 열에 따라 달라짐

`read_parquet_flat`은 쿼리가 쓰는 열의 노드만 읽고 join합니다. 리스트 열을 하나도 쓰지 않으면 최상위 행을 세고, 리스트 열을 쓰면 그 원소를 셉니다.
그래서 같은 flat 쿼리라도 바깥 쿼리가 리스트 열을 버리면 결과가 바뀝니다. builtin(UNNEST)은 바뀌지 않습니다.

```sql
-- data/distinct 에서, main_rey
SELECT count(*) AS n, sum(c11) AS s FROM read_parquet_flat('trade_A.parquet');
--   n = 1,672,940  (c11 원소 수)
SELECT n FROM (SELECT count(*) AS n, sum(c11) AS s FROM read_parquet_flat('trade_A.parquet'));
--   n = 249,728    (s를 버리자 c11 노드를 읽지 않고 최상위 행을 셈)
SELECT n FROM (SELECT count(*) AS n, sum(v) AS s FROM (SELECT unnest(c11) AS v FROM 'trade_A.parquet'));
--   n = 1,672,940  (builtin은 그대로)
```

`run_bench.py`의 결과 검사는 원래 첫 번째 열만 썼기 때문에 이 경우에 걸렸습니다(q4_one, q4_two의 flat이 "다름"으로 나옴). 지금은 모든 열을 쓰므로 측정하는 쿼리 그대로의 결과를 비교합니다.
