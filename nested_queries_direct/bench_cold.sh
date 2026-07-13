#!/usr/bin/env bash
#
# 콜드 캐시 벤치마크: nested_queries_direct 의 쿼리들을
#   main 브랜치 DuckDB  vs  projection 브랜치 DuckDB
# 로 각각 실행하며, 실행 전마다 페이지 캐시를 떨궈서
#   - 실제 디스크 읽기량 (File system inputs, /usr/bin/time -v)
#   - 벽시계 시간 (Elapsed)
# 을 잰다.
#
# 캐시 드롭에는 root 권한이 필요하므로 다음 중 하나로 실행:
#   sudo ./bench_cold.sh              # (권장) 스크립트 전체를 root 로 → 암호 한 번
#   ./bench_cold.sh                   # 일반 실행 → 드롭 때만 sudo 사용
#
# 특정 쿼리만: ./bench_cold.sh q1 q3 q16
# ---------------------------------------------------------------------------
set -u

# ---- 설정 (필요시 수정) ----------------------------------------------------
MAIN=/home/layun03/duckdb_main_wt/build/release/duckdb          # 수정 전 (main)
PROJ=/home/layun03/research_duckdb/build/release/duckdb         # 수정 후 (projection)
QDIR=/home/layun03/research_duckdb/nested_queries_direct        # 쿼리 폴더
OUT=$QDIR/results_cold.tsv                                      # 결과 저장(TSV)
TIME=/usr/bin/time                                             # GNU time (shell builtin 아님)
# ---------------------------------------------------------------------------

# ---- 사전 점검 -------------------------------------------------------------
for b in "$MAIN" "$PROJ"; do
  [ -x "$b" ] || { echo "ERROR: 바이너리 없음/실행불가: $b"; exit 1; }
done
[ -x "$TIME" ] || { echo "ERROR: GNU time 없음: $TIME  (설치: sudo apt install time)"; exit 1; }

# ---- 캐시 드롭 (root 면 직접, 아니면 sudo) ---------------------------------
drop_caches() {
  if [ -w /proc/sys/vm/drop_caches ]; then
    sync; echo 3 > /proc/sys/vm/drop_caches
  else
    sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' \
      || { echo "ERROR: 캐시 드롭 실패 (root/sudo 필요)"; exit 1; }
  fi
}

# ---- time -v 로그 파싱 -----------------------------------------------------
# File system inputs (512바이트 블록) → MB
get_inputs_mb() { awk -F': ' '/File system inputs/{printf "%.1f",$2*512/1048576}' "$1"; }
# Elapsed (wall clock)  [h:]m:s(.ss) → 초
get_wall_s() {
  awk -F': ' '/Elapsed \(wall clock\)/{
    n=split($2,a,":"); s=0; for(i=1;i<=n;i++) s=s*60+a[i]; printf "%.3f",s }' "$1"
}

# ---- 한 번 측정 (전역 R_MB, R_S 에 결과 저장; 서브셸/프로세스치환 사용 안 함) --
R_MB=""; R_S=""
measure() {   # $1=바이너리  $2=쿼리파일
  local bin="$1" q="$2" log
  log=$(mktemp)
  drop_caches
  "$TIME" -v "$bin" -batch -c ".read $q" >/dev/null 2>"$log"
  R_MB=$(get_inputs_mb "$log"); R_S=$(get_wall_s "$log")
  rm -f "$log"
}

# ---- 대상 쿼리 목록 (항상 배열로) ------------------------------------------
QUERIES=()
if [ "$#" -gt 0 ]; then
  for name in "$@"; do QUERIES+=("$QDIR/${name%.sql}.sql"); done
else
  while IFS= read -r line; do QUERIES+=("$line"); done < <(ls -1v "$QDIR"/q*.sql)
fi

# ---- 실행 ------------------------------------------------------------------
printf "query\tmain_MB\tmain_s\tproj_MB\tproj_s\tMB_saved\tspeedup\n" | tee "$OUT"
tot_mm=0; tot_pm=0; tot_ms=0; tot_ps=0
for q in "${QUERIES[@]}"; do
  [ -f "$q" ] || { echo "skip(없음): $q" >&2; continue; }
  name=$(basename "$q" .sql)
  measure "$MAIN" "$q"; mMB=$R_MB; mS=$R_S
  measure "$PROJ" "$q"; pMB=$R_MB; pS=$R_S
  saved=$(awk "BEGIN{printf \"%.1f\",$mMB-$pMB}")
  spd=$(awk "BEGIN{ if($pS>0) printf \"%.2fx\",$mS/$pS; else print \"n/a\" }")
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$name" "$mMB" "$mS" "$pMB" "$pS" "$saved" "$spd" | tee -a "$OUT"
  tot_mm=$(awk "BEGIN{print $tot_mm+$mMB}"); tot_pm=$(awk "BEGIN{print $tot_pm+$pMB}")
  tot_ms=$(awk "BEGIN{print $tot_ms+$mS}");  tot_ps=$(awk "BEGIN{print $tot_ps+$pS}")
done

# ---- 합계 ------------------------------------------------------------------
echo "----------------------------------------------------------------------"
awk "BEGIN{
  printf \"TOTAL  main=%.1fMB/%.2fs   proj=%.1fMB/%.2fs   I/O -%.1fMB (%.2fx less)   time %.2fx\n\",
    $tot_mm,$tot_ms,$tot_pm,$tot_ps,($tot_mm-$tot_pm),
    ($tot_pm>0?$tot_mm/$tot_pm:0),($tot_ps>0?$tot_ms/$tot_ps:0) }"
echo "결과 저장: $OUT"
echo "주의: 콜드 드롭은 DuckDB 바이너리 로드(~50MB)도 포함 → main/proj 양쪽에 같은 오프셋."
echo "      절대값보다 두 바이너리의 '차이(MB_saved)/배율(speedup)'이 유의미한 신호다."
