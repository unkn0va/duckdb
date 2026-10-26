# 연구실 서버에서 벤치마크 다시 재기

이 문서의 명령을 위에서부터 순서대로 복사해 붙이면 됩니다. 모든 파일은 홈 폴더 아래 `~/nested-bench/`에 둡니다.

```
~/nested-bench/
├── duckdb_rey/    main_rey 소스 (이 문서와 스크립트도 여기 있음) + release 빌드
├── duckdb_base/   원래 DuckDB 소스 (main_rey가 갈라져 나온 커밋) + release 빌드
├── venv/          데이터 생성용 Python 환경 (pyarrow 26.0.0)
└── data/          논문 데이터와 선택도 실험 데이터
```

**무엇을 재나요?**

| 구성 | 바이너리 | 쿼리 |
|---|---|---|
| builtin | 원래 DuckDB (커밋 `a809d3cd519`) | 중첩 타입을 UNNEST로 푸는 기존 방식 |
| flat | main_rey | `read_parquet_flat` (XMark는 `flat_minmax` 형태) |
| split (선택, 기본 꺼짐) | main_rey | 논문의 미리 쪼갠 파일 |

- 데이터셋은 TPC-H SF1, TPC-H SF10, XMark, DBLP, 그리고 선택도 실험 (A)와 (B)입니다.
- 쿼리마다 두 바이너리와 모든 스레드 수를 번갈아 실행하고, 10번 중 가장 빠른 시간을 씁니다.
- 선택도 실험에서 main_rey는 "query 설정"으로 돕니다. join이 만드는 필터를 쓰지 않는다는 뜻입니다.
- 실행이 끝나면 builtin과 flat의 결과가 쿼리마다 같은지 자동으로 확인합니다.

**걸리는 시간 (노트북 기준)**

| 단계 | 시간 |
|---|---|
| 빌드 (두 개) | 20–60분 |
| 데이터 받기 | 인터넷 속도에 따라 다름 (8.5 GB) |
| 측정, 1스레드 | 약 25분 |
| 측정, 그보다 큰 스레드 수 하나당 | 약 10분 |

- 스레드를 `"1 16 32 64"`로 주면 측정은 약 1시간입니다.
- `--split`을 켜면 1.5배 정도 걸립니다.

**필요한 디스크 공간**: 약 35 GB.
- 데이터 zip 8.5 GB와 압축을 푼 데이터 10 GB
- 생성 데이터 0.4 GB
- 소스와 빌드 약 2 × 5 GB

---

## 1. 필요한 프로그램 확인

아래를 붙여 넣으면 프로그램마다 `있음`/`없음`과, cmake·g++·python3의 버전이 나옵니다. `없음`이 나오는 줄이 있으면, 그 프로그램을 설치해 달라고 서버 관리자에게 부탁하세요.
- Ubuntu라면 `sudo apt install git cmake ninja-build g++ make python3 python3-venv tmux unzip curl` 한 줄로 설치됩니다.
- 버전 요구 사항: cmake 3.14 이상, C++17을 지원하는 g++ 또는 clang, Python 3.11 이상(pyarrow 26.0.0이 3.11부터 설치됩니다).
- 서버의 `python3`가 3.11보다 낮으면, 아래 venv를 만들 때 `python3` 대신 `python3.11`(또는 `python3.12`)을 쓰세요.
  없다면 관리자에게 설치를 부탁하세요. 측정 스크립트 자체는 Python 3.9 이상이면 됩니다.

```bash
for p in git cmake ninja g++ make python3 tmux unzip curl sha256sum; do
  if command -v $p >/dev/null; then echo "$p: 있음"; else echo "$p: 없음 <-- 설치 필요"; fi
done
cmake --version | head -1; g++ --version | head -1; python3 --version
python3 -c "import venv, ensurepip; print('python3-venv: 있음')" || echo "python3-venv(ensurepip): 없음 <-- '자주 생기는 문제' 참고"
echo "CPU: $(nproc) 스레드, 메모리: $(free -g | awk '/^Mem:/ {print $2}') GB, 홈 폴더 남은 공간: $(df -h ~ | awk 'NR==2 {print $4}')"
```

데이터 생성용 Python 환경을 만듭니다. `pyarrow`는 반드시 26.0.0이어야 노트북과 똑같은 파일이 만들어집니다. `gdown`은 Google Drive에서 데이터를 받는 데 씁니다.

```bash
mkdir -p ~/nested-bench
python3 -m venv ~/nested-bench/venv
~/nested-bench/venv/bin/pip install pyarrow==26.0.0 gdown
~/nested-bench/venv/bin/python -c "import pyarrow; print('pyarrow', pyarrow.__version__)"
```

마지막 줄이 `pyarrow 26.0.0`이면 됩니다.

## 2. 소스 받기와 release 빌드

**노트북에서 먼저 할 일**: main_rey 브랜치를 GitHub에 올립니다. 이 저장소의 원격은 `https://github.com/unkn0va/duckdb.git`이고, main_rey는 아직 올라가 있지 않습니다.

```bash
# 노트북의 저장소 폴더에서
git push origin main_rey
```

**서버에서**: 소스를 받습니다. 원래 DuckDB 커밋은 git worktree로 같은 저장소에서 꺼냅니다.

```bash
cd ~/nested-bench
git clone https://github.com/unkn0va/duckdb.git duckdb_rey
cd ~/nested-bench/duckdb_rey
git checkout main_rey
git log -1 --format="main_rey: %H %s"
# 원래 DuckDB = main_rey가 DuckDB main에서 갈라져 나온 커밋 (merge-base)
git merge-base --is-ancestor a809d3cd519df6db70223c562c4de80da311868b main_rey && echo "base 커밋 확인됨"
git worktree add ~/nested-bench/duckdb_base a809d3cd519df6db70223c562c4de80da311868b
```

`base 커밋 확인됨`이 나와야 합니다.

이제 두 소스를 release로 빌드합니다. 하나에 10–30분 걸립니다. 다른 사람과 같이 쓰는 서버라면 `CMAKE_BUILD_PARALLEL_LEVEL`을 코어 수의 절반쯤으로 줄이세요.

```bash
cd ~/nested-bench/duckdb_rey && CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) GEN=ninja make release
cd ~/nested-bench/duckdb_base && CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) GEN=ninja make release
```

빌드가 잘 됐는지 확인합니다.

```bash
~/nested-bench/duckdb_rey/build/release/duckdb -no-agent -c "SELECT library_version, source_id FROM pragma_version()"
~/nested-bench/duckdb_base/build/release/duckdb -no-agent -c "SELECT library_version, source_id FROM pragma_version()"
~/nested-bench/duckdb_rey/build/release/duckdb -no-agent -c "SELECT count(*) FROM duckdb_functions() WHERE function_name = 'read_parquet_flat'"
```

- 처음 두 줄은 버전과 커밋을 하나씩 보여 줍니다.
- 세 번째 줄은 `1`이 나와야 합니다. main_rey에만 있는 함수이기 때문입니다.
- 같은 명령을 base 바이너리에 실행하면 `0`이 나옵니다.

## 3. 데이터 받기

논문 저자가 올린 데이터 zip을 받습니다. 크기는 8,551,262,143 바이트이고, 저자 저장소 https://github.com/alicerey/nested-parquet 의 Google Drive 링크(https://drive.google.com/file/d/1UqwFbuywMErdgau1_JWN8QwzjMwpXle4)에서 받습니다. 아래 명령의 긴 문자열이 그 파일의 ID입니다.

```bash
mkdir -p ~/nested-bench/data && cd ~/nested-bench/data
~/nested-bench/venv/bin/gdown 1UqwFbuywMErdgau1_JWN8QwzjMwpXle4 -O nested-parquet-datasets.zip
```

Google Drive가 막으면("Too many users have viewed or downloaded this file" 등), 다른 컴퓨터에서 브라우저로 받아 서버로 복사하세요. 노트북에 이미 있는 zip을 복사해도 됩니다. 노트북에서 아래처럼 실행하고, `<서버>`를 `사용자@서버주소`로 바꾸세요.

```bash
rsync -av --progress nested-parquet-datasets.zip <서버>:~/nested-bench/data/
```

zip이 제대로 받아졌는지 체크섬으로 확인한 뒤 압축을 풉니다.

```bash
cd ~/nested-bench/data
echo "52f27386437266ae7a9b11d7d42baeff13fa8cea85311d09898c92c66f8fde02  nested-parquet-datasets.zip" | sha256sum -c -
unzip -q nested-parquet-datasets.zip && rm -rf __MACOSX
ls ~/nested-bench/data/nested-parquet-datasets
```

- 체크섬 줄은 `nested-parquet-datasets.zip: OK`가 나와야 합니다. `FAILED`가 나오면 다시 받으세요.
- 마지막 `ls`에 `dblp nested-tpch nested-tpch-sf10 synthetic xmark`가 보여야 합니다.

## 4. 데이터가 제대로 옮겨졌는지 확인

[data_manifest.tsv](data_manifest.tsv)에 모든 파일의 크기와 SHA-256 체크섬이 적혀 있습니다. 이 값은 노트북에서 계산했습니다. 확인은 두 단계로 합니다.

```bash
cd ~/nested-bench/duckdb_rey/benchmark/nested_parquet
python3 check_data.py ~/nested-bench/data --only nested-parquet-datasets/          # 크기만 (몇 초)
python3 check_data.py ~/nested-bench/data --only nested-parquet-datasets/ --full   # 체크섬까지 (몇 분)
```

- 둘 다 `OK: all 58 files present ...`로 끝나야 합니다.
- 문제가 있으면 `!!! DATA CHECK FAILED`와 함께 빠지거나 다른 파일 목록이 나옵니다.

## 5. 선택도 실험 데이터 만들기

`prepare_data.sh`가 두 가지를 만들고 확인합니다. 만든 파일은 노트북의 파일과 바이트 단위로 같아야 합니다.
- (A) 논문의 `l1.parquet`에서 잘라 낸 split 파일
- (B) `a`를 정렬한 데이터와 그 split 파일

```bash
cd ~/nested-bench/duckdb_rey/benchmark/nested_parquet
./prepare_data.sh ~/nested-bench/data ~/nested-bench/venv/bin/python
```

`OK: all 5 files present, sizes and SHA-256 checksums match.`로 끝나면 됩니다.

## 6. 짧은 시험 실행 (1분 이내)

본 측정 전에 모든 단계가 동작하는지 작게 시험합니다. 시험 결과는 따로 `/tmp/bench-smoke`에 둡니다.

```bash
cd ~/nested-bench/duckdb_rey/benchmark/nested_parquet
./run_all.sh --base ~/nested-bench/duckdb_base/build/release/duckdb \
             --final ~/nested-bench/duckdb_rey/build/release/duckdb \
             --data ~/nested-bench/data --threads "1 4" --runs 1 \
             --datasets "xmark selectivity_sorted" --out /tmp/bench-smoke
```

마지막에 다음 두 가지가 나오면 됩니다.
- `OK: all ... results equal the builtin results (or their oracles).`
- `Summary: /tmp/bench-smoke/summary.md`

**물리 코어 확인**
main_rey는 레벨을 세야 하는 스캔을 "row group 수 < min(스레드 수, 물리 코어 수)"일 때만 쪼갭니다. 그래서 DuckDB가 물리 코어를 제대로 세는지 확인합니다. 첫 줄은 운영체제가 보는 물리 코어 수입니다. 둘째 줄은 DuckDB가 TPC-H SF10 파일을 40스레드로 읽을 때 쓴 물리 코어 수와 쪼갰는지를 로그에서 보여 줍니다.

```bash
lscpu -p=CORE,SOCKET | grep -v '^#' | sort -u | wc -l
(cd ~/nested-bench/data/nested-parquet-datasets/nested-tpch-sf10 && ~/nested-bench/duckdb_rey/build/release/duckdb -no-agent -csv -noheader -c "SET threads = 40; CALL enable_logging(level := 'debug', storage := 'memory')" -c "SELECT count(_ak0) FROM read_parquet_node('nestedcustomer.parquet', node := 'c_orders')" -c "SELECT message FROM duckdb_logs WHERE message LIKE '%physical cores%'")
```

- 연구실 서버(소켓 2개 × 10코어)라면 첫 줄은 `20`입니다.
- 둘째 명령의 마지막 줄은 `... has 22 row groups, 40 threads run on 20 physical cores: the row groups are not split`이어야 합니다.
- 중간에 나오는 `WARNING: The logging settings have been changed ...`는 로그를 메모리에 모으도록 바꿨다는 안내라서 무시해도 됩니다.
- 두 수가 다르면 측정하지 말고 출력을 그대로 가져오세요.

## 7. 본 측정: tmux 안에서 실행

측정은 한 시간 넘게 걸립니다. SSH 연결이 끊겨도 계속 돌도록 tmux 안에서 실행하세요.

```bash
tmux new -s bench
```

tmux 화면이 열리면 아래를 붙여 넣습니다. `--threads`는 원하는 스레드 수로 바꾸세요. `nproc`가 보여 준 수보다 큰 값은 의미가 적습니다. 미리 쪼갠 파일(split)도 재려면 마지막 줄 끝에 ` --split`을 붙이세요.

```bash
cd ~/nested-bench/duckdb_rey/benchmark/nested_parquet
./run_all.sh --base ~/nested-bench/duckdb_base/build/release/duckdb \
             --final ~/nested-bench/duckdb_rey/build/release/duckdb \
             --data ~/nested-bench/data --threads "1 16 32 64"
```

- **tmux에서 빠져나오기**: `Ctrl-b`를 누르고 손을 뗀 뒤 `d`를 누릅니다. 측정은 계속 돕니다.
- **다시 들어가기**: `tmux attach -t bench`
- **진행 상황**: 화면에 데이터셋마다 `== tpch_sf1: started 14:02` 같은 줄이 나옵니다. 자세한 로그는 결과 폴더의 `logs/<데이터셋>.log`에 있습니다.
- **측정 중 주의**: 다른 무거운 작업을 하지 마세요. 빌드, 다른 실험, 큰 파일 복사 모두 측정을 오염시킵니다.

## 8. 결과 파일

결과는 `~/nested-bench/duckdb_rey/benchmark/nested_parquet/results_<날짜>_<시각>/`에 모입니다.

| 파일 | 내용 |
|---|---|
| `summary.md` | builtin / flat 배수 표: 데이터셋 × 스레드 요약, 쿼리별 표 |
| `result_check.txt` | 결과 비교: 쿼리마다 flat이 builtin(또는 oracle)과 같은지 |
| `<데이터셋>.csv` | 원자료: 구성·스레드별 가장 빠른 시간(`_s`), CPU 시간(`_cpu`), 결과 일치 여부(`_ok`) |
| `run_info.txt` | 서버, CPU, 두 바이너리의 커밋, 설정 |
| `logs/` | 데이터셋별 실행 로그 |

표만 다시 만들려면 아래처럼 실행합니다.

```bash
python3 summarize.py <결과 폴더>
python3 check_results.py <결과 폴더>
```

노트북으로 가져오려면 노트북에서 아래처럼 실행합니다.

```bash
rsync -av <서버>:~/nested-bench/duckdb_rey/benchmark/nested_parquet/results_<날짜>_<시각> .
```

**XMark Q2 등 원래 결과가 다른 경우**:
- flat은 자식이 없는 부모 행을 내지 않습니다. 예를 들어 입찰자가 없는 경매가 그렇습니다.
- 이런 쿼리는 `queries/<데이터셋>/<쿼리>.<변형>.oracle`의 기대 결과와 비교합니다. 그래서 "다름"으로 나오지 않습니다.

## 9. 쪼개기 기준 실험 (규칙 (a) 켬/끔)

> **2026-10-18에 끝난 실험입니다.**
> - 결과는 `server_20261018_split_rule/`에, 해석은 RESULTS.md의 "Hardware experiment and the final criterion"에 있습니다.
> - 이 결과로 정한 최종 기준은 "레벨을 세야 하면 row group 수 < min(스레드 수, 물리 코어 수)일 때만 쪼갠다"입니다.
> - 최종 버전에는 아래 명령이 쓰는 설정 `parquet_node_split_half_threads`가 없습니다. 같은 실험을 다시 하려면 2단계에서 main_rey 대신 커밋 `7f2e2261de3`을 빌드하세요.

**무엇을 보나요?**
- 규칙 (a)는 레벨을 세야 하는 스캔에서, row group이 스레드의 절반 이하를 차지할 때만 row group을 쪼개는 규칙입니다. 설정 `parquet_node_split_half_threads`(기본 켬)로 켜고 끕니다. 끄면 전처럼 "row group 수 < 스레드 수"이면 쪼갭니다.
- 2026-10-18 서버 측정에서 이 규칙은 TPC-H SF10의 40스레드(row group 22개)는 빠르게 했지만, DBLP의 10스레드(row group 6개)는 느리게 했습니다.
- 두 경우의 "row group 수 / 스레드 수"는 0.55와 0.6으로 거의 같습니다. 그래서 차이는 이 비율보다 하드웨어에서 왔을 가능성이 큽니다.
  - SF10 40스레드는 20코어를 넘어 하이퍼스레드를 쓰고 두 소켓에 걸칩니다.
  - DBLP 10스레드는 한 소켓의 코어 안에 들어갈 수 있습니다.
- 이 실험은 그 원인을 가립니다. main_rey 바이너리 하나로, 설정만 켬(`on`)과 끔(`off`)으로 바꿔 번갈아 잽니다.

**준비**: main_rey를 최신으로 받아 다시 빌드합니다(원래 DuckDB는 필요 없습니다).

```bash
cd ~/nested-bench/duckdb_rey && git pull && CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) GEN=ninja make release
```

**측정 (약 1시간)**: tmux 안에서 실행하세요(7단계).
- SF10과 DBLP의 flat 쿼리를 threads 10, 20, 30, 40에서 `on`/`off`로 번갈아 잽니다.
- 이어서 DBLP를 10스레드로, CPU 배치를 세 가지로 고정해 한 번 더 잽니다.
  - `one`: 한 소켓의 코어 10개
  - `two`: 두 소켓의 코어 5개씩
  - `ht`: 한 소켓의 코어 5개 × 하이퍼스레드 2개
- 끊겼다면 같은 명령을 다시 붙여 넣으면 됩니다. 끝난 데이터셋은 건너뜁니다.

```bash
cd ~/nested-bench/duckdb_rey/benchmark/nested_parquet
B=~/nested-bench/duckdb_rey/build/release/duckdb
DATA=~/nested-bench/data/nested-parquet-datasets
OUT=~/nested-bench/results_split_rule
ON="SET parquet_node_split_half_threads = true"
OFF="SET parquet_node_split_half_threads = false"
mkdir -p $OUT
for spec in "tpch_sf10 nested-tpch-sf10" "dblp dblp"; do
  set -- $spec
  [ -f $OUT/$1.csv ] && continue
  RUNS=10 THREADS=10,20,30,40 VARIANTS="on=flat off=flat" \
    python3 run_bench.py "on=$B;$ON,off=$B;$OFF" queries/$1 $DATA/$2 $OUT/$1.csv > $OUT/$1.log 2>&1 \
    || { echo "STOPPED: see $OUT/$1.log"; break; }
done
python3 cpu_layouts.py 10 | tee $OUT/cpu_layouts.txt
BINS="" LABELS=""
while read layout cpus; do
  printf '#!/bin/sh\nexec taskset -c %s %s "$@"\n' "$cpus" "$B" > $OUT/duckdb_$layout && chmod +x $OUT/duckdb_$layout
  BINS="$BINS,on_$layout=$OUT/duckdb_$layout;$ON,off_$layout=$OUT/duckdb_$layout;$OFF"
  LABELS="$LABELS on_$layout=flat off_$layout=flat"
done < $OUT/cpu_layouts.txt
[ -f $OUT/dblp_pinned.csv ] || RUNS=10 THREADS=10 VARIANTS="$LABELS" \
  python3 run_bench.py "${BINS#,}" queries/dblp $DATA/dblp $OUT/dblp_pinned.csv > $OUT/dblp_pinned.log 2>&1 \
  || echo "STOPPED: see $OUT/dblp_pinned.log"
python3 split_rule_table.py $OUT $B ~/nested-bench/data | tee $OUT/table.md
```

- 마지막 줄은 표를 `table.md`로 만듭니다. 쿼리와 설정마다 한 번씩 더 실행해서 쪼갠 row group 수를 읽기 때문에 몇 분 걸립니다.
- `cpu_layouts.txt`에 세 배치의 CPU 번호가 나옵니다. 서버에 없는 배치(예: 소켓이 하나)는 빠집니다.
- 결과 폴더를 노트북으로 가져올 때는 8단계의 rsync 명령에서 폴더 이름만 `results_split_rule`로 바꾸세요.

**표 읽는 법** (`table.md`)
- 열은 `on`과 `off`의 시간(CPU 시간), `off/on`, 그리고 각 설정에서 쪼갠 row group 수입니다. 괄호 안은 그중 레벨을 세는 수입니다.
- `off/on` < 1이면 쪼개는 쪽(`off`)이 빠르다는 뜻입니다.
- `<<` 표시가 있는 줄만 계획이 다릅니다.
  - SF10: 30·40스레드의 q03, q04, q12
  - DBLP: 10스레드 전부와 `one`/`two`/`ht` 줄
  - 나머지 줄(SF10 10·20스레드, q01·q06, DBLP 20스레드 이상)은 두 설정의 계획이 같습니다. 이 줄들의 `off/on`이 1에서 벗어난 정도가 측정 잡음입니다. 표 끝의 `Noise` 줄에 나옵니다.
- 잡음보다 큰 차이만 의미가 있습니다. 경우별 해석은 다음과 같습니다.

| 관찰 | 해석 | 기준 |
|---|---|---|
| DBLP `ht` 줄만 `off/on` > 1이고, `one`·`two`는 < 1 | 레벨 세기를 하며 쪼개면 하이퍼스레드를 같이 쓸 때 손해 | 스레드 수가 물리 코어 수 이하일 때만 쪼갬 |
| DBLP `two` 줄만 `off/on` > 1이고, `one`은 < 1 | 두 소켓에 걸칠 때(NUMA) 손해 | 한 소켓의 코어 수 이하일 때만 쪼갬 |
| `one`·`two`·`ht` 모두 < 1이고, SF10 30·40스레드는 > 1 | 하드웨어 배치와 상관없이 SF10에서만 손해 | 이유를 따로 찾아야 함 (SF10은 파일 형식이 parquet-mr, row group당 page 수가 다름) |
| SF10 30스레드는 < 1, 40스레드만 > 1 | 하이퍼스레드를 많이 쓸수록 손해 | 하이퍼스레드 쪽 기준과 같음 |
| DBLP 10스레드(배치 고정 없음)가 `one`과 같고 `two`와 다름 | 서버가 10스레드를 보통 한 소켓에 둠 | 위 해석을 그대로 적용 |

## 10. 1스레드 빌드 차이 실험

**무엇을 보나요?**
- 최종 서버 측정(2026-10-19)에서 1스레드 builtin/flat 배수가 모든 데이터셋에서 1차 측정(2026-10-17)보다 조금씩 낮아졌습니다(예: TPC-H SF1 16.35x → 15.36x).
- builtin 시간은 그대로였으니, flat이 조금 느려졌다는 뜻입니다.
- 1스레드 경로의 코드는 바뀌지 않았으니 빌드 차이로 보았습니다. 그런데 모든 칸이 같은 방향이어서, 이 실험으로 정말 빌드 차이인지 확인합니다.

| 이름 | 바이너리 |
|---|---|
| A1 | 최종 커밋 `924a47be83`을 새 폴더에서 빌드 |
| A2 | 같은 커밋 `924a47be83`을 또 다른 새 폴더에서 빌드 |
| B | 1차 측정 커밋 `787dcd6d1b`을 새 폴더에서 빌드 |
| base | 원래 DuckDB(이미 있는 `~/nested-bench/duckdb_base`), builtin 쿼리로 측정 환경 확인 |

- 전체 데이터셋을 1스레드로만 잽니다.
- 쿼리마다 네 바이너리를 번갈아 실행하고, 10번 중 가장 빠른 시간을 씁니다.
- 이미 있는 `~/nested-bench/duckdb_rey`와 `~/nested-bench/duckdb_base` 폴더의 파일은 바꾸지 않습니다.
  - 새 폴더는 `git worktree`로 `~/nested-bench/build_diff/` 아래에 만듭니다.
  - `~/nested-bench/duckdb_rey/.git`에는 worktree 목록과 `git fetch`로 받은 원격 브랜치 정보만 추가됩니다. 마지막 정리 단계에서 worktree 목록을 지웁니다.

**시간과 디스크**

| 단계 | 시간 | 디스크 |
|---|---|---|
| 빌드 세 개 (차례로) | 하나에 9–10분 (노트북 기준, 서버는 더 빠를 수 있음), 합계 약 30분 | 하나에 약 1.5 GB (소스와 빌드), 합계 약 4.5 GB |
| 측정 | 약 1시간 (TPC-H SF10이 40분) | 몇 MB |

시작 전에 `df -h ~`로 빈 공간이 6 GB 이상인지 확인하세요.

**10-1. worktree 만들기와 빌드** (tmux 안에서 실행하세요. 7단계 참고)

```bash
cd ~/nested-bench/duckdb_rey
git fetch origin
mkdir -p ~/nested-bench/build_diff
git worktree add --detach ~/nested-bench/build_diff/a1 924a47be83
git worktree add --detach ~/nested-bench/build_diff/a2 924a47be83
git worktree add --detach ~/nested-bench/build_diff/b 787dcd6d1b
git show origin/main_rey:benchmark/nested_parquet/build_diff_table.py > ~/nested-bench/build_diff/build_diff_table.py
for w in a1 a2 b; do
  (cd ~/nested-bench/build_diff/$w && CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) GEN=ninja make release > ../build_$w.log 2>&1) \
    && echo "$w: $(~/nested-bench/build_diff/$w/build/release/duckdb -no-agent -csv -noheader -c "SELECT source_id FROM pragma_version()")" \
    || { echo "$w: build failed, see ~/nested-bench/build_diff/build_$w.log"; break; }
done
```

- 끝나면 `a1: 924a47be83`, `a2: 924a47be83`, `b: 787dcd6d1b` 세 줄이 나옵니다.
- 빌드가 실패해서 다시 실행할 때는 `git worktree add` 세 줄을 빼고, `for` 줄부터 붙여 넣으세요. 이미 빌드된 부분은 다시 하지 않습니다.

**10-2. 측정** (약 1시간, tmux 안에서)

```bash
cd ~/nested-bench/build_diff/a1/benchmark/nested_parquet
BASE=~/nested-bench/duckdb_base/build/release/duckdb
A1=~/nested-bench/build_diff/a1/build/release/duckdb
A2=~/nested-bench/build_diff/a2/build/release/duckdb
B=~/nested-bench/build_diff/b/build/release/duckdb
DATA=~/nested-bench/data
OUT=~/nested-bench/build_diff/results
QUERY_SETUP="SET disabled_optimizers = 'join_filter_pushdown';SET parquet_node_join_filter_pruning = false"
mkdir -p $OUT
for spec in "tpch_sf1 nested-parquet-datasets/nested-tpch" "xmark nested-parquet-datasets/xmark" \
            "dblp nested-parquet-datasets/dblp" "tpch_sf10 nested-parquet-datasets/nested-tpch-sf10" \
            "selectivity_random selectivity_random" "selectivity_sorted selectivity_sorted"; do
  set -- $spec
  [ -f $OUT/$1.csv ] && continue
  SETUP=""; case $1 in selectivity_*) SETUP=";$QUERY_SETUP" ;; esac
  RUNS=10 THREADS=1 VARIANTS="base=builtin a1=flat,flat_minmax a2=flat,flat_minmax b=flat,flat_minmax" \
    python3 run_bench.py "base=$BASE,a1=$A1$SETUP,a2=$A2$SETUP,b=$B$SETUP" queries/$1 $DATA/$2 $OUT/$1.csv \
    > $OUT/$1.log 2>&1 || { echo "STOPPED: see $OUT/$1.log"; break; }
  echo "$1 done $(date +%H:%M)"
done
```

- 선택도 실험은 본 측정과 같이 A1·A2·B에 "query 설정"을 줍니다.
- `STOPPED`가 나오면 다른 프로세스가 CPU를 쓰는 중입니다("자주 생기는 문제" 참고). 끝날 때까지 기다린 뒤 같은 블록을 다시 붙여 넣으세요. 끝난 데이터셋은 건너뜁니다.

**10-3. 표 만들기**

```bash
ls -d ~/nested-bench/results_* ~/nested-bench/duckdb_rey/benchmark/nested_parquet/results_* 2>/dev/null
python3 ~/nested-bench/build_diff/build_diff_table.py ~/nested-bench/build_diff/results \
  --earlier first=<1차 측정 결과 폴더> --earlier final=~/nested-bench/results_final \
  | tee ~/nested-bench/build_diff/results/table.md
```

- 첫 줄은 이전 측정 결과 폴더를 보여 줍니다.
  - 1차 측정(2026-10-17, `run_info.txt`의 final이 `787dcd6d1b`)의 폴더를 `<1차 측정 결과 폴더>` 자리에 넣으세요.
  - 폴더가 없으면 해당 `--earlier` 옵션을 빼도 됩니다.
- 노트북으로 가져오기: `rsync -av <서버>:~/nested-bench/build_diff/results ~/build_diff_results`

**표 읽는 법** (`table.md`)

데이터셋마다 쿼리별 표가 있고, 끝에 요약 표가 있습니다.
- 쿼리별 표: 네 바이너리의 시간(초), `a2/a1`, `b/a1`, 결과 일치 여부가 나옵니다.
- 요약 표: 데이터셋마다 `a2/a1`과 `b/a1`의 기하평균, 가장 큰 `a2/a1` 차이, builtin이 이전 측정과 같은지가 나옵니다.

1. **측정 환경 확인**: 요약 표의 `builtin now / earlier`가 1에 가까우면(±5% 안), 서버가 이전 측정 때와 같은 속도로 돕니다.
   - 크게 다르면 서버 상태(다른 사용자, CPU 주파수)가 달라진 것입니다.
   - 그때는 이전 측정과 비교하지 말고, 이번 측정 안에서 A1·A2·B만 비교하세요.
2. **빌드 차이의 크기**: `a2/a1`이 1에서 벗어난 정도입니다. 같은 코드를 다시 빌드했을 때 생기는 차이입니다.
   - "largest a2/a1 difference" 열에서 데이터셋마다 가장 큰 차이를 볼 수 있습니다.
3. **판정**: `b/a1`을 2번의 크기와 비교합니다.

| 관찰 | 해석 |
|---|---|
| `b/a1`이 1에서 벗어난 정도가 `a2/a1`의 차이 범위 안 | 1차와 최종의 1스레드 차이는 빌드 차이가 맞음 |
| `b/a1`이 대부분의 데이터셋에서 그 범위보다 확실히 크고, 쿼리 대부분에서 같은 방향(예: 마지막 줄 `b is faster than a1 in`이 거의 전부) | 787dcd6d1b → 924a47be83 사이의 코드 변경 때문. 원인을 찾아야 함 |
| `a2/a1`도 쿼리 대부분에서 한쪽으로 치우침 | 빌드 차이 자체가 체계적으로 크다는 뜻. 1차와 최종의 차이를 설명할 수 있는지 크기로 판단 |

- 1차 측정에서 flat이 더 빨랐으니, 코드 변경 때문이라면 `b/a1` < 1(B가 빠름)로 나옵니다.

**10-4. 정리** (결과를 가져온 뒤, 약 4.5 GB 확보)

```bash
cd ~/nested-bench/duckdb_rey
for w in a1 a2 b; do git worktree remove --force ~/nested-bench/build_diff/$w; done
git worktree list
```

`git worktree list`에 `~/nested-bench/duckdb_rey` 한 줄만 남으면 됩니다. `~/nested-bench/build_diff/results`와 빌드 로그는 남아 있습니다.

## 11. 명령어 수 비교 (A1 vs B)

**무엇을 보나요?**
- 10단계에서 B(1차 커밋 `787dcd6d1b`)가 1스레드의 모든 flat 쿼리에서 A1(최종 커밋 `924a47be83`)보다 평균 5% 빨랐습니다.
- 그 사이에 바뀐 코드는 1스레드 스캔에서는 실행되지 않습니다. 그래서 두 가지 가능성이 있습니다.
  - A1이 실제로 일을 더 하는지
  - 같은 일을 하는데 코드 배치 때문에 느린지
- `perf stat`으로 실행한 명령어 수(instructions)와 CPU 사이클(cycles)을 세어 둘을 가립니다.
- 바뀐 `column_reader.cpp`는 DuckDB의 기존 Parquet 읽기(`read_parquet`)도 씁니다. 그래서 flat뿐 아니라 builtin 쿼리도 A1과 B로 각각 잽니다. 우리 변경이 일반 Parquet 읽기까지 느리게 했는지 보기 위해서입니다.
- 10단계의 a1, b worktree와 바이너리를 그대로 씁니다. 10-4 정리를 아직 하지 않았어야 합니다.

**걸리는 시간**: 11-0 1분, 11-1 약 10분, 11-2 약 20분. 디스크는 거의 쓰지 않습니다.

**11-0. perf를 쓸 수 있는지 확인**

```bash
which perf && perf --version
cat /proc/sys/kernel/perf_event_paranoid
perf stat -e instructions:u,cycles:u -- true
```

- 마지막 명령의 출력에 `instructions:u`와 `cycles:u` 두 줄이 숫자와 함께 나오면 쓸 수 있습니다. 11-1로 가세요.
- 안 될 때:

| 증상 | 원인 | 대안 |
|---|---|---|
| `perf: command not found` | perf가 설치되지 않음 | 관리자에게 설치를 부탁합니다(Ubuntu: `linux-tools-$(uname -r)`, Debian: `linux-perf`). |
| `No permission` / `Access to performance monitoring and observability operations is limited`, 둘째 줄이 3 이상 | 커널이 일반 사용자의 카운터 사용을 막음 | 관리자에게 `sudo sysctl kernel.perf_event_paranoid=2`를 부탁합니다(재부팅하면 원래대로 돌아갑니다). 2 이하면 자기 프로세스의 사용자 영역 카운터(`:u`)를 쓸 수 있습니다. |
| `<not supported>` | 가상 머신 등에서 하드웨어 카운터가 없음 | 아래 valgrind 대안을 씁니다. |

- **관리자 도움 없이 하는 대안 (valgrind가 있을 때)**: `which valgrind`로 확인합니다.
  - callgrind는 실행한 명령어 수를 정확히 셉니다. 사이클은 세지 않습니다.
  - 그래서 명령어 수는 callgrind로 보고, 시간은 10단계 결과와 11-2를 씁니다.
  - 한 번 실행이 수십 배 느려지므로 짧은 쿼리만 잽니다.

  ```bash
  cd ~/nested-bench/build_diff/a1/benchmark/nested_parquet
  for q in xmark/q02.flat_minmax xmark/q02.builtin selectivity_random/n6.builtin; do
    d=$(dirname $q); case $d in xmark) dir=nested-parquet-datasets/xmark ;; *) dir=$d ;; esac
    printf 'SET threads = 1;\n.mode trash\n%s\n' "$(cat queries/$q.sql)" > ~/nested-bench/build_diff/cg.sql
    for w in a1 b; do
      echo "$q $w: $(cd ~/nested-bench/data/$dir && valgrind --tool=callgrind --callgrind-out-file=/dev/null \
        ~/nested-bench/build_diff/$w/build/release/duckdb -no-agent -f ~/nested-bench/build_diff/cg.sql 2>&1 | grep -o 'Collected : [0-9]*')"
    done
  done
  ```

  `Collected : <수>`가 실행한 명령어 수입니다. a1과 b의 수를 비교하세요.

**11-1. 명령어 수와 사이클** (약 10분)

쿼리마다 a1과 b를 번갈아 5번씩 실행하고, 가장 작은 값을 씁니다. 한 번 실행은 프로세스 하나가 쿼리를 3번 반복하는 것입니다. flat 쿼리 5개와 builtin 쿼리 4개를 잽니다.

```bash
cd ~/nested-bench/duckdb_rey && git fetch origin
git show origin/main_rey:benchmark/nested_parquet/perf_compare.py > ~/nested-bench/build_diff/perf_compare.py
cd ~/nested-bench/build_diff/a1/benchmark/nested_parquet
python3 ~/nested-bench/build_diff/perf_compare.py perf \
  --binary a1=$HOME/nested-bench/build_diff/a1/build/release/duckdb \
  --binary b=$HOME/nested-bench/build_diff/b/build/release/duckdb \
  --queries queries --data $HOME/nested-bench/data \
  --setup "SET disabled_optimizers = 'join_filter_pushdown';SET parquet_node_join_filter_pruning = false;" \
  tpch_sf1/q06.flat tpch_sf1/q12.flat xmark/q02.flat_minmax selectivity_random/n6.flat selectivity_sorted/n1.flat \
  tpch_sf1/q06.builtin xmark/q02.builtin dblp/q08.builtin selectivity_random/n6.builtin \
  | tee ~/nested-bench/build_diff/results/perf.md
```

- 표에 쿼리마다 a1과 b의 instructions, cycles, 그 비율(b/a1), IPC(사이클당 명령어 수)가 나옵니다.
- 어떤 줄에 `ERROR`가 나오면 11-0의 확인을 다시 해 보세요.

**11-2. builtin 시간 비교** (약 20분)

10단계는 builtin을 원래 DuckDB(base)로만 쟀습니다. 여기서는 builtin을 A1과 B로 번갈아 잽니다. 10회 중 최솟값을 쓰고, TPC-H SF10은 오래 걸려서 뺍니다.

```bash
cd ~/nested-bench/build_diff/a1/benchmark/nested_parquet
A1=~/nested-bench/build_diff/a1/build/release/duckdb
B=~/nested-bench/build_diff/b/build/release/duckdb
DATA=~/nested-bench/data
OUT=~/nested-bench/build_diff/builtin_ab
mkdir -p $OUT
for spec in "tpch_sf1 nested-parquet-datasets/nested-tpch" "xmark nested-parquet-datasets/xmark" \
            "dblp nested-parquet-datasets/dblp" "selectivity_random selectivity_random" \
            "selectivity_sorted selectivity_sorted"; do
  set -- $spec
  [ -f $OUT/$1.csv ] && continue
  RUNS=10 THREADS=1 VARIANTS="a1=builtin b=builtin" \
    python3 run_bench.py "a1=$A1,b=$B" queries/$1 $DATA/$2 $OUT/$1.csv > $OUT/$1.log 2>&1 \
    || { echo "STOPPED: see $OUT/$1.log"; break; }
  echo "$1 done $(date +%H:%M)"
done
python3 ~/nested-bench/build_diff/perf_compare.py table $OUT | tee $OUT/table.md
```

노트북으로 가져오기 (노트북에서):

```bash
rsync -av <서버>:~/nested-bench/build_diff/results/perf.md <서버>:~/nested-bench/build_diff/builtin_ab ~/build_diff_results/
```

**결과 읽는 법**

11-1의 `instructions b/a1`과 `cycles b/a1`을 봅니다. 시간 비율은 10단계의 `b/a1`(flat)과 11-2의 표(builtin)에 있습니다.

| instructions b/a1 | cycles b/a1 | 해석 |
|---|---|---|
| 1에 가까움 (±0.5% 안) | 1보다 작음 (시간 비율과 비슷) | **코드 배치**: 두 바이너리가 같은 명령어를 실행하지만, A1이 사이클당 명령어를 덜 처리합니다(IPC a1 < IPC b). 명령어 캐시, 분기 예측, 루프 정렬처럼 코드가 메모리에 놓인 위치에 따른 차이입니다. |
| 1보다 작음 (시간 비율과 비슷) | 비슷하게 작음 | **실제 추가 작업**: A1이 명령어를 더 실행합니다. 10단계 (2)처럼 사이의 커밋을 하나씩 빌드해서 원인 커밋을 찾아야 합니다. |

builtin은 따로 봅니다.
- builtin도 B가 빠르면(11-2의 `b/a1` < 1, 11-1의 builtin cycles도 B가 적음), 우리 변경이 DuckDB의 일반 Parquet 읽기에도 영향을 준 것입니다.
  - 명령어 수가 같으면 코드 배치 때문이고, 다르면 일반 읽기 경로에서 일이 늘어난 것입니다.
- builtin이 차이가 없으면(`b/a1` ≈ 1), 영향은 `read_parquet_node` 쪽에만 있습니다.

## 자주 생기는 문제

**시작이 거부됨: `STOPPED: other processes keep the CPU busy`**
- 측정 직전에 CPU를 확인했더니, 다른 프로세스가 세 번 연속 코어 반 개 이상을 쓰고 있었다는 뜻입니다. 그 상태로 재면 숫자를 믿을 수 없습니다.
- `top`(나갈 때는 `q`)으로 무엇이 돌고 있는지 봅니다. 자기 프로세스라면 끝내고, 다른 사람의 작업이라면 끝날 때까지 기다리세요.
- 그다음 **같은 명령을 그대로 다시** 실행합니다. 이미 끝난 데이터셋은 건너뛰고 이어서 잽니다(`== ...: already done`).
- 어쩔 수 없이 부하가 있는 채로 재야 한다면 명령 앞에 `ALLOW_BUSY=1 `을 붙입니다. 이때는 결과 CSV의 `busy_cpu` 열에 부하가 기록되니, 숫자를 해석할 때 감안하세요.

**측정 중간에 끊김** (SSH 끊김 없이 서버가 재시작되거나, 실수로 Ctrl-C를 누른 경우)
- 같은 명령에 `--out <끊긴 결과 폴더>`를 붙여 다시 실행하면, 끝난 데이터셋은 건너뜁니다.
- 끊긴 데이터셋은 처음부터 다시 잽니다. 중간 결과는 `<데이터셋>.csv.partial`에 남아 있습니다.
- 끊길 때 돌던 DuckDB 프로세스는 스크립트가 정리합니다. 혹시 남았는지는 `pgrep -a duckdb`로 확인하고, 남았다면 `pkill duckdb`로 끝내세요.

**`!!! RESULT CHECK FAILED`**
- 어떤 쿼리에서 flat의 결과가 builtin과 달랐거나, 쿼리가 실패 또는 시간 초과됐다는 뜻입니다. 그 쿼리의 시간은 비교에 쓰면 안 됩니다.
- 출력에 데이터셋, 쿼리, 변형이 나옵니다. 로그(`logs/<데이터셋>.log`)에서 그 쿼리의 줄을 찾아 보세요.
- 데이터가 손상됐을 수도 있으니 4단계의 `--full` 확인을 다시 해 보세요.
- 그래도 다르면 결과 폴더를 통째로 노트북으로 가져와 분석합니다.

**venv 생성 실패: `ensurepip is not available`**
- 서버의 Python에 pip을 설치하는 모듈(ensurepip)이 없어서 생기는 오류입니다. Debian/Ubuntu에서 `python3-venv` 패키지가 빠진 경우입니다.
- 관리자에게 `python3-venv`(예: `python3.12-venv`) 설치를 부탁하거나, 관리자 권한 없이 아래처럼 pip 없이 venv를 만든 뒤 pip을 따로 설치합니다.
- 실패한 venv 폴더가 남아 있으면 먼저 지웁니다. 첫 줄의 `rm -rf`가 그 일을 합니다.

  ```bash
  rm -rf ~/nested-bench/venv
  python3 -m venv --without-pip ~/nested-bench/venv
  curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  ~/nested-bench/venv/bin/python /tmp/get-pip.py
  ~/nested-bench/venv/bin/pip install pyarrow==26.0.0 gdown
  ~/nested-bench/venv/bin/python -c "import pyarrow; print('pyarrow', pyarrow.__version__)"
  ```

- 마지막 줄이 `pyarrow 26.0.0`이면 1단계의 venv 만들기가 끝난 것이니 2단계로 넘어가세요.
- Python 3.11 미만이라 `python3.11` 등을 쓰는 경우에는 둘째 줄의 `python3`도 그 이름으로 바꾸세요.

**데이터 받기가 중간에 끊김**
- gdown은 받던 내용을 `nested-parquet-datasets.zip....part`라는 파일에 남깁니다.
- 3단계의 gdown 명령에 ` --continue`를 붙여 다시 실행하면 이어서 받습니다.
- 그다음 체크섬 확인부터 다시 하세요.

**`!!! DATA CHECK FAILED`**
- `MISSING`: 압축을 풀지 않았거나 다른 폴더에 풀었습니다. `~/nested-bench/data/nested-parquet-datasets/`가 있어야 합니다.
- `WRONG SIZE` 또는 `WRONG SHA256`: 파일이 덜 받아졌거나 손상됐습니다. zip을 다시 받아 3단계부터 다시 하세요.
- `selectivity_...` 파일이 다르다면: pyarrow가 26.0.0이 아닐 가능성이 큽니다(1단계). 다른 버전으로 만든 파일도 측정에는 쓸 수 있지만, 노트북 결과와 같은 파일은 아닙니다.

**빌드 실패**
- `c++: fatal error: Killed` 또는 메모리 부족: 동시에 컴파일하는 수를 줄여 다시 실행합니다. 이미 빌드된 부분은 다시 하지 않습니다.
  ```bash
  CMAKE_BUILD_PARALLEL_LEVEL=4 GEN=ninja make release
  ```
- cmake나 컴파일러가 너무 오래됐다는 오류: 1단계의 버전 요구 사항을 확인하고, 관리자에게 설치를 부탁하세요.
- `make release`를 두 폴더에서 동시에 돌리지 마세요. 하나씩 하는 편이 메모리 문제가 덜합니다.

**쿼리가 시간 초과됨**
- 쿼리 한 번의 제한은 기본 600초입니다. 아주 느린 서버라면 명령 앞에 `QUERY_TIMEOUT=1800 `을 붙입니다.

**결과가 노트북과 크게 다름**
- 서버의 다른 사용자, CPU 주파수 조절, NUMA 때문에 시간이 흔들릴 수 있습니다.
- 같은 결과 폴더 안에서 builtin과 flat을 번갈아 쟀기 때문에, 둘 사이의 배수는 서로 비교할 수 있습니다.
- 서로 다른 실행 사이의 절대 시간은 비교하지 마세요.
