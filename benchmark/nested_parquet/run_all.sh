#!/usr/bin/env bash
# Run the whole nested Parquet benchmark (SERVER.md, step 7): the builtin queries with the original DuckDB and the
# flat queries (XMark: flat_minmax) with main_rey, every query interleaved between the two binaries and all thread
# counts, fastest of RUNS runs; then the selectivity experiment the same way (main_rey with the "query" settings: no
# join filter pushdown). Afterwards the results are checked (check_results.py) and summarized (summarize.py).
#
# Usage: run_all.sh --base <duckdb of the original DuckDB> --final <duckdb of main_rey> --data <data folder>
#                   --threads "1 16 32 64" [--out <results folder>] [--runs 10] [--split] [--datasets "..."] [--force]
#   --out       where the results go (default: results_<date>_<time> next to this script)
#   --runs      runs per query and configuration; the fastest counts (default 10)
#   --split     also run the paper's pre-split files (split variant) with main_rey
#   --datasets  default "tpch_sf1 xmark dblp tpch_sf10 selectivity_random selectivity_sorted"
#   --force     run datasets again whose results already exist in --out (by default they are skipped, so that an
#               interrupted run can be resumed with the same command)
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
BASE="" FINAL="" DATA="" THREADS="" OUT="" RUNS=10 SPLIT=0 FORCE=0
DATASETS="tpch_sf1 xmark dblp tpch_sf10 selectivity_random selectivity_sorted"
usage() { sed -n '2,15p' "$0"; exit 2; }
while [ $# -gt 0 ]; do
	case "$1" in
	--base) BASE=$2; shift 2 ;;
	--final) FINAL=$2; shift 2 ;;
	--data) DATA=$2; shift 2 ;;
	--threads) THREADS=$2; shift 2 ;;
	--out) OUT=$2; shift 2 ;;
	--runs) RUNS=$2; shift 2 ;;
	--datasets) DATASETS=$2; shift 2 ;;
	--split) SPLIT=1; shift ;;
	--force) FORCE=1; shift ;;
	*) echo "unknown option: $1"; usage ;;
	esac
done
[ -n "$BASE" ] && [ -n "$FINAL" ] && [ -n "$DATA" ] && [ -n "$THREADS" ] || usage
for binary in "$BASE" "$FINAL"; do
	[ -x "$binary" ] || { echo "ERROR: $binary is not an executable file (SERVER.md, step 2)"; exit 1; }
done
[ -d "$DATA/nested-parquet-datasets" ] || { echo "ERROR: $DATA/nested-parquet-datasets not found (SERVER.md, step 3)"; exit 1; }
BASE=$(cd "$(dirname "$BASE")" && pwd)/$(basename "$BASE")
FINAL=$(cd "$(dirname "$FINAL")" && pwd)/$(basename "$FINAL")
DATA=$(cd "$DATA" && pwd)
OUT=${OUT:-$HERE/results_$(date +%Y%m%d_%H%M)}
mkdir -p "$OUT/logs"
OUT=$(cd "$OUT" && pwd)

# the folder of a dataset in the data folder, and the prefix of its files in data_manifest.tsv
data_dir() {
	case "$1" in
	tpch_sf1) echo "nested-parquet-datasets/nested-tpch" ;;
	tpch_sf10) echo "nested-parquet-datasets/nested-tpch-sf10" ;;
	xmark | dblp) echo "nested-parquet-datasets/$1" ;;
	selectivity_random | selectivity_sorted) echo "$1" ;;
	*) echo "" ;;
	esac
}

version() { "$1" -no-agent -csv -noheader -c "SELECT concat_ws(' ', library_version, source_id) FROM pragma_version()" 2>&1; }

VARIANTS="base=builtin final=flat,flat_minmax"
[ "$SPLIT" = 1 ] && VARIANTS="$VARIANTS,split"
QUERY_SETUP="SET disabled_optimizers = 'join_filter_pushdown';SET parquet_node_join_filter_pruning = false"

{
	echo "date:      $(date -Is)"
	echo "host:      $(hostname)"
	echo "cpu:       $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs) ($(nproc) hardware threads)"
	echo "memory:    $(free -g | awk '/^Mem:/ {print $2}') GiB"
	echo "base:      $(version "$BASE")  $BASE"
	echo "final:     $(version "$FINAL")  $FINAL"
	echo "data:      $DATA"
	echo "threads:   $THREADS"
	echo "runs:      $RUNS"
	echo "variants:  $VARIANTS"
	echo "datasets:  $DATASETS"
} | tee "$OUT/run_info.txt"

STARTED=$(date +%s)
for dataset in $DATASETS; do
	dir=$(data_dir "$dataset")
	[ -n "$dir" ] || { echo "ERROR: unknown dataset $dataset"; exit 1; }
	if [ -f "$OUT/$dataset.csv" ] && [ "$FORCE" = 0 ]; then
		echo "== $dataset: already done ($OUT/$dataset.csv), skipped"
		continue
	fi
	if ! python3 "$HERE/check_data.py" "$DATA" --only "$dir/" > "$OUT/logs/$dataset.data_check.txt"; then
		cat "$OUT/logs/$dataset.data_check.txt"
		echo "ERROR: the data of $dataset is incomplete - see SERVER.md, steps 3-5."
		exit 1
	fi
	binaries="base=$BASE,final=$FINAL"
	[[ $dataset == selectivity_* ]] && binaries="base=$BASE,final=$FINAL;$QUERY_SETUP"
	echo "== $dataset: started $(date +%H:%M), log: $OUT/logs/$dataset.log"
	RUNS=$RUNS THREADS=$(echo "$THREADS" | xargs | tr ' ' ',') VARIANTS=$VARIANTS \
		python3 "$HERE/run_bench.py" "$binaries" "$HERE/queries/$dataset" "$DATA/$dir" "$OUT/$dataset.csv" \
		> "$OUT/logs/$dataset.log" 2>&1
	status=$?
	grep -E "^(WARNING|ERROR)" -A6 "$OUT/logs/$dataset.log" | head -20
	if [ $status -eq 2 ]; then
		echo "STOPPED: other processes keep the CPU busy (see above) - the benchmark of $dataset did not start."
		echo "Wait until they are done (check with: top) and run the same command again; finished datasets are kept."
		echo "SERVER.md, 'Common problems', explains what to do."
		exit 2
	elif [ $status -eq 130 ] || [ $status -eq 143 ] || [ $status -eq 129 ]; then
		echo "INTERRUPTED: the benchmark of $dataset was stopped (Ctrl-C, kill or a closed terminal); the queries it"
		echo "finished are in $OUT/$dataset.csv.partial (if any). Run the same command with --out $OUT to resume."
		exit 130
	elif [ $status -ne 0 ]; then
		echo "ERROR: $dataset failed (exit status $status), see $OUT/logs/$dataset.log"
		exit 1
	fi
	echo "   done after $((($(date +%s) - STARTED) / 60)) min"
done

echo
python3 "$HERE/summarize.py" "$OUT" > "$OUT/summary.md"
echo "Summary: $OUT/summary.md"
python3 "$HERE/check_results.py" "$OUT" | tee "$OUT/result_check.txt"
check=${PIPESTATUS[0]}
echo "Results: $OUT"
exit "$check"
