#!/usr/bin/env bash
# Issue 2: join estimates (README.md). Every step writes into --out:
#   info         run_info.txt
#   variants     2-1: variants.csv (time_queries.py over queries_plans/: q1_s01, q1_s50, q6_group, q7_csa, q7_plots x
#                orig / fixed / preagg x five configurations, RUNS at 1 thread, results compared with the original
#                query; a variant whose plan equals the original's is not timed again) and variant_plans/ (EXPLAIN
#                ANALYZE of every timed one)
#   cardinality  2-2: cardinality.csv (cardinality.py: estimated and actual rows of every join, UNNEST and input scan)
#                of the 40 trade queries in all five configurations and of the earlier datasets' builtin and flat
#                queries (TPC-H SF1, SF10, XMark, DBLP, selectivity) - CARD_THREADS threads, one run each
#   summary      summary.md (summarize_issue2.py)
#
# Usage: run_issue2.sh [--data <trade data folder>] [--out <folder>] [--steps "info variants cardinality summary"]
# Environment: RUNS (10), CARD_THREADS (20), ORIG_DATA ($NB/data), ALLOW_BUSY, BASE, PRENEST, FINAL, NB
set -uo pipefail

NB=${NB:-$HOME/nested-bench}
BASE=${BASE:-$NB/duckdb_base/build/release/duckdb}
PRENEST=${PRENEST:-$NB/duckdb_prenest_base/build/release/duckdb}
FINAL=${FINAL:-$NB/duckdb_rey/build/release/duckdb}
export BASE PRENEST FINAL
ORIG_DATA=${ORIG_DATA:-$NB/data}
RUNS=${RUNS:-10}
CARD_THREADS=${CARD_THREADS:-20}

HERE=$(cd "$(dirname "$0")" && pwd)
TRADE=$(cd "$HERE/.." && pwd)
DATA=$TRADE/data/full OUT=$HERE/server_issue2_$(date +%Y%m%d_%H%M) STEPS="info variants cardinality summary"
while [ $# -gt 0 ]; do
	case "$1" in
	--data) DATA=$2; shift 2 ;;
	--out) OUT=$2; shift 2 ;;
	--steps) STEPS=$2; shift 2 ;;
	*) sed -n '2,15p' "$0"; exit 2 ;;
	esac
done
DATA=$(cd "$DATA" && pwd)
mkdir -p "$OUT" && OUT=$(cd "$OUT" && pwd)
log() { echo "[$(date +%T)] $*"; }
version() { "$1" -no-agent -noheader -list -c "SELECT library_version || ' ' || source_id FROM pragma_version()"; }

for step in $STEPS; do
	log "step $step"
	case $step in
	info)
		{
			echo "date:     $(date -Iseconds)"
			echo "host:     $(hostname), $(nproc) hardware threads, $(free -g | awk '/^Mem:/ {print $2}') GiB memory"
			echo "cpu:      $(lscpu | sed -n 's/^Model name: *//p')"
			echo "uptime:   $(uptime)"
			echo "base:     $(version "$BASE")  $BASE"
			echo "prenest:  $(version "$PRENEST")  $PRENEST"
			echo "final:    $(version "$FINAL")  $FINAL"
			echo "scripts:  $(git -C "$HERE" log -1 --format='%h %s' 2>/dev/null)"
			echo "data:     $DATA, earlier datasets $ORIG_DATA"
			echo "runs:     $RUNS at 1 thread (variants), cardinality at $CARD_THREADS threads"
		} | tee "$OUT/run_info.txt"
		;;
	variants)
		RUNS=$RUNS THREADS=1 SAME_PLAN=1 PLAN_DIR="$OUT/variant_plans" python3 "$HERE/time_queries.py" \
			"$HERE/queries_plans" "$DATA" "$OUT/variants.csv" | tee "$OUT/variants.log"
		;;
	cardinality)
		rm -f "$OUT/cardinality.csv"
		THREADS=$CARD_THREADS VARIANTS="builtin flat split" python3 "$HERE/cardinality.py" \
			trade "$TRADE/queries" "$DATA" "$OUT/cardinality.csv" | tee "$OUT/cardinality.log"
		flat_setup="SET disabled_optimizers = 'join_filter_pushdown'; SET parquet_node_join_filter_pruning = false;"
		while read -r dataset dir; do
			[ -d "$ORIG_DATA/$dir" ] || { log "no $ORIG_DATA/$dir, $dataset skipped" | tee -a "$OUT/cardinality.log"; continue; }
			setup=""
			[[ $dataset == selectivity_* ]] && setup=$flat_setup
			THREADS=$CARD_THREADS VARIANTS="builtin flat flat_minmax flat_umbra" FLAT_SETUP="$setup" \
				python3 "$HERE/cardinality.py" "$dataset" "$TRADE/../queries/$dataset" "$ORIG_DATA/$dir" \
				"$OUT/cardinality.csv" | tee -a "$OUT/cardinality.log"
		done <<'EOF'
tpch_sf1 nested-parquet-datasets/nested-tpch
tpch_sf10 nested-parquet-datasets/nested-tpch-sf10
xmark nested-parquet-datasets/xmark
dblp nested-parquet-datasets/dblp
selectivity_random selectivity_random
selectivity_sorted selectivity_sorted
EOF
		;;
	summary)
		python3 "$HERE/summarize_issue2.py" "$OUT" >"$OUT/summary.md" && log "summary: $OUT/summary.md"
		;;
	*)
		log "unknown step $step"; exit 2 ;;
	esac
done
log "done: $OUT"
