# 연구실 서버에서 벤치마크 다시 재기

이 문서의 명령을 위에서부터 순서대로 복사해 붙이면 됩니다. 모든 파일은 홈 폴더 아래 `~/nested-bench/`에 둡니다.

```
~/nested-bench/
├── duckdb/        main_rey 소스 (이 문서와 스크립트도 여기 있음) + release 빌드
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
git clone https://github.com/unkn0va/duckdb.git duckdb
cd ~/nested-bench/duckdb
git checkout main_rey
git log -1 --format="main_rey: %H %s"
# 원래 DuckDB = main_rey가 DuckDB main에서 갈라져 나온 커밋 (merge-base)
git merge-base --is-ancestor a809d3cd519df6db70223c562c4de80da311868b main_rey && echo "base 커밋 확인됨"
git worktree add ~/nested-bench/duckdb_base a809d3cd519df6db70223c562c4de80da311868b
```

`base 커밋 확인됨`이 나와야 합니다.

이제 두 소스를 release로 빌드합니다. 하나에 10–30분 걸립니다. 다른 사람과 같이 쓰는 서버라면 `CMAKE_BUILD_PARALLEL_LEVEL`을 코어 수의 절반쯤으로 줄이세요.

```bash
cd ~/nested-bench/duckdb && CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) GEN=ninja make release
cd ~/nested-bench/duckdb_base && CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) GEN=ninja make release
```

빌드가 잘 됐는지 확인합니다.

```bash
~/nested-bench/duckdb/build/release/duckdb -no-agent -c "SELECT library_version, source_id FROM pragma_version()"
~/nested-bench/duckdb_base/build/release/duckdb -no-agent -c "SELECT library_version, source_id FROM pragma_version()"
~/nested-bench/duckdb/build/release/duckdb -no-agent -c "SELECT count(*) FROM duckdb_functions() WHERE function_name = 'read_parquet_flat'"
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
cd ~/nested-bench/duckdb/benchmark/nested_parquet
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
cd ~/nested-bench/duckdb/benchmark/nested_parquet
./prepare_data.sh ~/nested-bench/data ~/nested-bench/venv/bin/python
```

`OK: all 5 files present, sizes and SHA-256 checksums match.`로 끝나면 됩니다.

## 6. 짧은 시험 실행 (1분 이내)

본 측정 전에 모든 단계가 동작하는지 작게 시험합니다. 시험 결과는 따로 `/tmp/bench-smoke`에 둡니다.

```bash
cd ~/nested-bench/duckdb/benchmark/nested_parquet
./run_all.sh --base ~/nested-bench/duckdb_base/build/release/duckdb \
             --final ~/nested-bench/duckdb/build/release/duckdb \
             --data ~/nested-bench/data --threads "1 4" --runs 1 \
             --datasets "xmark selectivity_sorted" --out /tmp/bench-smoke
```

마지막에 다음 두 가지가 나오면 됩니다.
- `OK: all ... results equal the builtin results (or their oracles).`
- `Summary: /tmp/bench-smoke/summary.md`

## 7. 본 측정: tmux 안에서 실행

측정은 한 시간 넘게 걸립니다. SSH 연결이 끊겨도 계속 돌도록 tmux 안에서 실행하세요.

```bash
tmux new -s bench
```

tmux 화면이 열리면 아래를 붙여 넣습니다. `--threads`는 원하는 스레드 수로 바꾸세요. `nproc`가 보여 준 수보다 큰 값은 의미가 적습니다. 미리 쪼갠 파일(split)도 재려면 마지막 줄 끝에 ` --split`을 붙이세요.

```bash
cd ~/nested-bench/duckdb/benchmark/nested_parquet
./run_all.sh --base ~/nested-bench/duckdb_base/build/release/duckdb \
             --final ~/nested-bench/duckdb/build/release/duckdb \
             --data ~/nested-bench/data --threads "1 16 32 64"
```

- **tmux에서 빠져나오기**: `Ctrl-b`를 누르고 손을 뗀 뒤 `d`를 누릅니다. 측정은 계속 돕니다.
- **다시 들어가기**: `tmux attach -t bench`
- **진행 상황**: 화면에 데이터셋마다 `== tpch_sf1: started 14:02` 같은 줄이 나옵니다. 자세한 로그는 결과 폴더의 `logs/<데이터셋>.log`에 있습니다.
- **측정 중 주의**: 다른 무거운 작업을 하지 마세요. 빌드, 다른 실험, 큰 파일 복사 모두 측정을 오염시킵니다.

## 8. 결과 파일

결과는 `~/nested-bench/duckdb/benchmark/nested_parquet/results_<날짜>_<시각>/`에 모입니다.

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
rsync -av <서버>:~/nested-bench/duckdb/benchmark/nested_parquet/results_<날짜>_<시각> .
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
cd ~/nested-bench/duckdb && git pull && CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) GEN=ninja make release
```

**측정 (약 1시간)**: tmux 안에서 실행하세요(7단계).
- SF10과 DBLP의 flat 쿼리를 threads 10, 20, 30, 40에서 `on`/`off`로 번갈아 잽니다.
- 이어서 DBLP를 10스레드로, CPU 배치를 세 가지로 고정해 한 번 더 잽니다.
  - `one`: 한 소켓의 코어 10개
  - `two`: 두 소켓의 코어 5개씩
  - `ht`: 한 소켓의 코어 5개 × 하이퍼스레드 2개
- 끊겼다면 같은 명령을 다시 붙여 넣으면 됩니다. 끝난 데이터셋은 건너뜁니다.

```bash
cd ~/nested-bench/duckdb/benchmark/nested_parquet
B=~/nested-bench/duckdb/build/release/duckdb
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
