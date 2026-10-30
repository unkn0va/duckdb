#!/usr/bin/env bash
# Issue 1: the cost of unnesting, broken down (README.md). Every step writes into --out:
#   info     run_info.txt: host, CPU, binaries, perf
#   stages   1-1: stage_check.md (the plans stop at the intended step), stage_time.csv (time_queries.py, RUNS at 1
#            thread, results compared), stage_plans/ (EXPLAIN ANALYZE), profile/stage/ (perf of every stage query)
#   params   1-2: counts.csv (lists and elements per query) and profile/params/ (perf of PARAM_QUERIES)
#   tpch     1-3: profile/tpch/ (perf of TPC-H SF1 and SF10 q01, q06 in base, prenestoff, flat)
#   summary  summary.md (summarize_issue1.py over everything present in --out)
# perf: 1 thread, FREQ Hz, user stacks (profile_stacks.py); per run <query>.<config>.txt and .folded.gz, and one row
# per category in profile.csv.
#
# Usage: run_issue1.sh [--data <trade data folder>] [--out <folder>] [--steps "info stages params tpch summary"]
# Environment: RUNS (10), PERF ("perf" or "sudo perf"), FREQ (1000), PARAM_QUERIES, ORIG_DATA ($NB/data), ALLOW_BUSY,
#              BASE, PRENEST, FINAL, NB
set -uo pipefail

NB=${NB:-$HOME/nested-bench}
BASE=${BASE:-$NB/duckdb_base/build/release/duckdb}
PRENEST=${PRENEST:-$NB/duckdb_prenest_base/build/release/duckdb}
FINAL=${FINAL:-$NB/duckdb_rey/build/release/duckdb}
export BASE PRENEST FINAL
PERF=${PERF:-perf}
export FREQ=${FREQ:-1000}
PARAM_QUERIES=${PARAM_QUERIES:-q2_c01 q2_c10 q2_c25 q2_c50 q2_c75 q3_c13 q3_c12 q3_c11 q1_s01 q1_s50 q1_s90 q2_s50}
ORIG_DATA=${ORIG_DATA:-$NB/data}
RUNS=${RUNS:-10}

HERE=$(cd "$(dirname "$0")" && pwd)
TRADE=$(cd "$HERE/.." && pwd)
DATA=$TRADE/data/full OUT=$HERE/server_issue1_$(date +%Y%m%d_%H%M) STEPS="info stages params tpch summary"
while [ $# -gt 0 ]; do
	case "$1" in
	--data) DATA=$2; shift 2 ;;
	--out) OUT=$2; shift 2 ;;
	--steps) STEPS=$2; shift 2 ;;
	*) sed -n '2,16p' "$0"; exit 2 ;;
	esac
done
DATA=$(cd "$DATA" && pwd)
mkdir -p "$OUT" && OUT=$(cd "$OUT" && pwd)
log() { echo "[$(date +%T)] $*"; }
version() { "$1" -no-agent -noheader -list -c "SELECT library_version || ' ' || source_id FROM pragma_version()"; }

# configuration label -> binary|setup|variant
config() {
	case $1 in
	base) echo "$BASE||builtin" ;;
	prenestoff) echo "$PRENEST|SET parquet_prenest_auto = false;|builtin" ;;
	prenest) echo "$PRENEST|SET parquet_prenest_auto = true;|builtin" ;;
	flat) echo "$FINAL||flat" ;;
	pureflat) echo "$BASE||split" ;;
	esac
}

perf_works() {
	local probe
	probe=$(mktemp -d)
	if ! $PERF record -q --call-graph dwarf -o "$probe/perf.data" -- true >"$probe/log" 2>&1; then
		log "WARNING: '$PERF record --call-graph dwarf' does not work here:"
		sed 's/^/    /' "$probe/log" | head -5
		rm -rf "$probe"
		return 1
	fi
	rm -rf "$probe"
}

# profile <folder> <data dir> <query dir> <query name> <config> ...: one perf run per configuration
profile() {
	local dir=$1 data=$2 queries=$3 query=$4
	shift 4
	mkdir -p "$dir"
	[ -f "$dir/profile.csv" ] || echo "query,config,wall_ms,cpu_ms,category,sub,cpu_ms_category" >"$dir/profile.csv"
	for label in "$@"; do
		IFS='|' read -r binary setup variant <<<"$(config "$label")"
		local file=$queries/$query.$variant.sql
		[ -f "$file" ] || { log "  $query $label: no $file, skipped"; continue; }
		log "profile $(basename "$dir") $query $label"
		THREADS=1 PERF="$PERF" SETUP="$setup" CSV_OUT="$dir/profile.csv" LABEL="$query,$label" \
			python3 "$HERE/profile_stacks.py" "$binary" "$data" "$file" "$dir/$query.$label" >/dev/null 2>"$dir/$query.$label.err" \
			|| log "  failed: $(tail -1 "$dir/$query.$label.err")"
		[ -s "$dir/$query.$label.err" ] || rm -f "$dir/$query.$label.err"
	done
}

ALL="base prenestoff prenest flat pureflat"
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
			echo "perf:     $($PERF version 2>&1)  ($PERF)"
			echo "scripts:  $(git -C "$HERE" log -1 --format='%h %s' 2>/dev/null)"
			echo "data:     $DATA"
			echo "runs:     $RUNS, perf $FREQ Hz"
		} | tee "$OUT/run_info.txt"
		;;
	stages)
		python3 "$HERE/stage_check.py" "$HERE/queries_stage" "$DATA" | tee "$OUT/stage_check.md"
		if grep '^| s[0-9]' "$OUT/stage_check.md" | grep -qv '| ok |$'; then
			log "WARNING: a stage query does not stop where it should, see stage_check.md"
		fi
		RUNS=$RUNS THREADS=1 PLAN_DIR="$OUT/stage_plans" python3 "$HERE/time_queries.py" "$HERE/queries_stage" "$DATA" \
			"$OUT/stage_time.csv" | tee "$OUT/stage_time.log"
		perf_works || continue
		for stage in s1_box s2_unnest s2f_fields s3_cond; do
			profile "$OUT/profile/stage" "$DATA" "$HERE/queries_stage" $stage $ALL
		done
		;;
	params)
		files=""
		for q in $PARAM_QUERIES; do files="$files $TRADE/queries/$q.builtin.sql"; done
		# shellcheck disable=SC2086
		python3 "$HERE/counts.py" "$DATA" "$OUT/counts.csv" $files
		perf_works || continue
		for q in $PARAM_QUERIES; do
			profile "$OUT/profile/params" "$DATA" "$TRADE/queries" "$q" $ALL
		done
		;;
	tpch)
		perf_works || continue
		for set in "tpch_sf1 nested-parquet-datasets/nested-tpch" "tpch_sf10 nested-parquet-datasets/nested-tpch-sf10"; do
			read -r name dir <<<"$set"
			[ -d "$ORIG_DATA/$dir" ] || { log "no $ORIG_DATA/$dir, $name skipped"; continue; }
			for q in q01 q06; do
				profile "$OUT/profile/$name" "$ORIG_DATA/$dir" "$TRADE/../queries/$name" $q base prenestoff flat
			done
		done
		;;
	summary)
		python3 "$HERE/summarize_issue1.py" "$OUT" >"$OUT/summary.md" && log "summary: $OUT/summary.md"
		;;
	*)
		log "unknown step $step"; exit 2 ;;
	esac
done
log "done: $OUT"
