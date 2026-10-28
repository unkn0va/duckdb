#!/usr/bin/env bash
# Measure the trade queries (README.md, step 3) on a data folder of prepare_trade.sh. Every step writes into --out:
#   info         run_info.txt: host, CPU, memory, the binaries' versions and commits, pyarrow
#   check        check_queries.md: results of the five configurations equal, prenest counters, joins of the plans
#   selectivity  selectivity.md: the share of rows and elements each query passes
#   bench        bench.csv (run_bench.py: base / prenestoff / prenest on the builtin queries, flat on the flat ones,
#                pure flat = base on the split ones; THREADS, fastest of RUNS) and query_times.csv (one row per query and
#                thread count, the columns of final_results.xlsx's "쿼리별 시간" for five configurations)
#   explain      operators_t1.csv: EXPLAIN ANALYZE at 1 thread, time per operator kind, every query and configuration
#   profile      profile/: perf samples at 1 thread of PROFILE_QUERIES in all five configurations, CPU time per category
#                (profile_breakdown.py: value decoding / list assembly / pre-nest filter / unnest / hash join / ...);
#                skipped with a warning when PERF cannot sample. Not in the default steps.
#   recheck      recheck/: the query sets of followup_20261027_0127 (TPC-H SF1/SF10, XMark, DBLP, selectivity, and the
#                rg1/rg20 files) once at 1 thread with the run_bench.py that compares every column of a result - results
#                only, no timing. Not in the default steps.
#
# Usage: run_trade.sh [--data <folder>] [--out <folder>] [--steps "info check selectivity bench explain profile recheck"]
# Environment: RUNS (10), THREADS (1,20), QUERY_TIMEOUT (seconds per query and configuration, 7200),
#              PERF ("perf" or "sudo perf"), PROFILE_QUERIES, ORIG_DATA (the data folder of ../SERVER.md, $NB/data)
set -uo pipefail

# ---- binaries: the paths of followup_20261027_0127/run_info.txt
NB=${NB:-$HOME/nested-bench}
BASE=${BASE:-$NB/duckdb_base/build/release/duckdb}
PRENEST=${PRENEST:-$NB/duckdb_prenest_base/build/release/duckdb}
FINAL=${FINAL:-$NB/duckdb_rey/build/release/duckdb}
PY=${PY:-$NB/venv/bin/python}
export BASE PRENEST FINAL
# perf command for the profile step: "perf", or "sudo perf" where perf_event_paranoid blocks users
PERF=${PERF:-perf}
PROFILE_QUERIES=${PROFILE_QUERIES:-q1_s50 q2_m50 q2_s50 q3_c11 q4_two q7_plots}
# data of the earlier runs (../SERVER.md): the paper's datasets and the selectivity data, and the rewritten rg1/rg20 files
ORIG_DATA=${ORIG_DATA:-$NB/data}
# ----

HERE=$(cd "$(dirname "$0")" && pwd)
DATA=$HERE/data/full OUT=$HERE/server_$(date +%Y%m%d_%H%M) STEPS="info check selectivity bench explain"
RUNS=${RUNS:-10} THREADS=${THREADS:-1,20}
export QUERY_TIMEOUT=${QUERY_TIMEOUT:-7200}
while [ $# -gt 0 ]; do
	case "$1" in
	--data) DATA=$2; shift 2 ;;
	--out) OUT=$2; shift 2 ;;
	--steps) STEPS=$2; shift 2 ;;
	*) sed -n '2,23p' "$0"; exit 2 ;;
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
			echo "base:     $(version "$BASE")  $BASE"
			echo "prenest:  $(version "$PRENEST")  $PRENEST"
			echo "final:    $(version "$FINAL")  $FINAL"
			echo "pyarrow:  $("$PY" -c 'import pyarrow; print(pyarrow.__version__)')"
			echo "data:     $DATA"
			echo "runs:     $RUNS, threads $THREADS"
		} | tee "$OUT/run_info.txt"
		;;
	check)
		"$PY" -I "$HERE/check_queries.py" "$HERE/queries" "$DATA" | tee "$OUT/check_queries.md"
		;;
	selectivity)
		"$PY" -I "$HERE/selectivity.py" "$BASE" "$DATA/trade_A.parquet" | tee "$OUT/selectivity.md"
		;;
	bench)
		RUNS=$RUNS THREADS=$THREADS VARIANTS="base=builtin,split prenestoff=builtin prenest=builtin final=flat" \
			python3 "$HERE/../run_bench.py" \
			"base=$BASE,prenestoff=$PRENEST;SET parquet_prenest_auto = false,prenest=$PRENEST;SET parquet_prenest_auto = true,final=$FINAL" \
			"$HERE/queries" "$DATA" "$OUT/bench.csv" >"$OUT/bench.log" 2>&1
		status=$?
		[ $status = 0 ] || { log "run_bench.py failed ($status), see $OUT/bench.log"; exit $status; }
		THREADS=$THREADS python3 "$HERE/summarize_trade.py" "$OUT/bench.csv" "trade $(basename "$DATA")" "$OUT/query_times.csv"
		;;
	explain)
		THREADS=1 "$PY" -I "$HERE/operator_times.py" "$HERE/queries" "$DATA" "$OUT/operators_t1.csv"
		;;
	profile)
		mkdir -p "$OUT/profile"
		probe=$(mktemp -d)
		if ! $PERF record -q -o "$probe/perf.data" -- true >"$probe/log" 2>&1; then
			log "WARNING: '$PERF record' does not work here - profile step skipped:"
			sed 's/^/    /' "$probe/log" | head -5
			rm -rf "$probe"
			continue
		fi
		rm -rf "$probe"
		echo "label,wall_ms,category,cpu_ms" >"$OUT/profile/profile.csv"
		for query in $PROFILE_QUERIES; do
			for config in "base|$BASE||builtin" "prenestoff|$PRENEST|SET parquet_prenest_auto = false;|builtin" \
				"prenest|$PRENEST|SET parquet_prenest_auto = true;|builtin" "flat|$FINAL||flat" "pureflat|$BASE||split"; do
				IFS='|' read -r label binary setup variant <<<"$config"
				log "profile $query $label"
				THREADS=1 PERF="$PERF" SETUP="$setup" CSV_OUT="$OUT/profile/profile.csv" LABEL="$query,$label" \
					PERF_DATA="$OUT/profile/$query.$label.perf.data" \
					python3 "$HERE/../profile_breakdown.py" "$binary" "$DATA" "$HERE/queries/$query.$variant.sql" \
					>"$OUT/profile/$query.$label.txt" 2>&1 || log "  failed, see $OUT/profile/$query.$label.txt"
			done
		done
		;;
	recheck)
		# dataset, folder below the data folder, file of the rg1/rg20 rewrite (followup_checks.sh)
		datasets="tpch_sf1 nested-parquet-datasets/nested-tpch nestedregion.parquet
tpch_sf10 nested-parquet-datasets/nested-tpch-sf10 nestedcustomer.parquet
xmark nested-parquet-datasets/xmark sf10.parquet
dblp nested-parquet-datasets/dblp dblp.parquet
selectivity_random selectivity_random l1.parquet
selectivity_sorted selectivity_sorted l1.parquet"
		query_setup="SET disabled_optimizers = 'join_filter_pushdown';SET parquet_node_join_filter_pruning = false"
		for layout in orig rg1 rg20; do
			root=$ORIG_DATA
			[ $layout = orig ] || root=$NB/data_$layout
			mkdir -p "$OUT/recheck/$layout"
			while read -r dataset dir file; do
				[ -f "$root/$dir/$file" ] || { log "recheck $layout $dataset: no $root/$dir/$file, skipped"; continue; }
				log "recheck $layout $dataset"
				final=$FINAL
				[[ $dataset == selectivity_* ]] && final="$FINAL;$query_setup"
				RUNS=1 THREADS=1 VARIANTS="base=builtin prenestoff=builtin prenest=builtin final=flat,flat_minmax" \
					python3 "$HERE/../run_bench.py" \
					"base=$BASE,prenestoff=$PRENEST;SET parquet_prenest_auto = false,prenest=$PRENEST;SET parquet_prenest_auto = true,final=$final" \
					"$HERE/../queries/$dataset" "$root/$dir" "$OUT/recheck/$layout/$dataset.csv" \
					>"$OUT/recheck/$layout/$dataset.log" 2>&1 || log "  run_bench.py failed, see $OUT/recheck/$layout/$dataset.log"
			done <<<"$datasets"
		done
		python3 "$HERE/recheck_results.py" "$OUT/recheck" | tee "$OUT/recheck/summary.md"
		;;
	*)
		log "unknown step $step"; exit 2 ;;
	esac
done
log "done: $OUT"
