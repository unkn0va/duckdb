#!/usr/bin/env bash
# Follow-ups G1-G4: measure what the report still estimates. Every step writes into --out:
#   check  check.txt: perf version, whether TopdownL1 (perf stat -M), cycles / branch-misses and /usr/bin/time work
#   g2     q4_two with the larger (orig) or the smaller (small_build) list built, base and prenest:
#          profile/g2/ (perf with stacks: categories and the phases of the hash table, categories.join_phase) and
#          g2_stat.csv (perf stat page faults, cycles, task-clock; maximum RSS from /usr/bin/time -v)
#   g1     branch mispredictions: g1_topdown.csv (TOPDOWN metric group + cycles) and g1_branches.csv (branch-misses)
#          of q2_c01..c75 in base, prenestoff, prenest, flat; trade_Bsorted next to trade_B (write_trade.py
#          --sort-legs, if missing; its time and memory in g1_sorted_write.txt), g1_sorted_verify.md,
#          g1_sorted_time.csv (q2_c50 on B and Bsorted, RUNS), profile/g1sorted/, g1_sorted_branches.csv
#   g3     DuckDB table vs parquet: profile/g3/ (k = 4, aggregation first, (a) parquet and (c) both DuckDB tables, base
#          and prenest; needs ../fanout/fanout.duckdb of run_issue2.sh fanout, made here if missing) and the stage
#          queries s1, s2, s3 on both (g3_stage_parquet.csv, g3_stage_db.csv, RUNS, base / prenestoff / prenest)
#   g4     synthetic lists of length 1..32 (make_syn.py, SYN_LISTS lists, g4_files.md), g4_time.csv (RUNS, base /
#          prenestoff / flat) and profile/g4/
#   summary  summary.md (summarize_g.py)
#
# Usage: run_followup2.sh [--data <trade data folder>] [--out <folder>] [--steps "check g2 g1 g3 g4 summary"]
# Environment: RUNS (10), PERF ("perf" or "sudo perf"), FREQ (1000), SYN_LISTS (100000000),
#              TOPDOWN (TopdownL1; "raw" = uops_issued.any, uops_retired.retire_slots, int_misc.recovery_cycles),
#              ALLOW_BUSY, PY, BASE, PRENEST, FINAL, NB
set -uo pipefail

NB=${NB:-$HOME/nested-bench}
BASE=${BASE:-$NB/duckdb_base/build/release/duckdb}
PRENEST=${PRENEST:-$NB/duckdb_prenest_base/build/release/duckdb}
FINAL=${FINAL:-$NB/duckdb_rey/build/release/duckdb}
PY=${PY:-$NB/venv/bin/python}
export BASE PRENEST FINAL PY
export PERF=${PERF:-perf}
export FREQ=${FREQ:-1000}
TOPDOWN=${TOPDOWN:-TopdownL1}
RUNS=${RUNS:-10}

HERE=$(cd "$(dirname "$0")" && pwd)
TRADE=$(cd "$HERE/.." && pwd)
DATA=$TRADE/data/full OUT=$HERE/server_followup2_$(date +%Y%m%d_%H%M) STEPS="check g2 g1 g3 g4 summary"
while [ $# -gt 0 ]; do
	case "$1" in
	--data) DATA=$2; shift 2 ;;
	--out) OUT=$2; shift 2 ;;
	--steps) STEPS=$2; shift 2 ;;
	*) sed -n '2,24p' "$0"; exit 2 ;;
	esac
done
DATA=$(cd "$DATA" && pwd)
mkdir -p "$OUT" && OUT=$(cd "$OUT" && pwd)
log() { echo "[$(date +%T)] $*"; }

config() {
	case $1 in
	base) echo "$BASE||builtin" ;;
	prenestoff) echo "$PRENEST|SET parquet_prenest_auto = false;|builtin" ;;
	prenest) echo "$PRENEST|SET parquet_prenest_auto = true;|builtin" ;;
	flat) echo "$FINAL||flat" ;;
	pureflat) echo "$BASE||split" ;;
	esac
}

# profile <folder> <query dir> <query name> <config> ...: perf with stacks, one run per configuration
profile() {
	local dir=$1 queries=$2 query=$3
	shift 3
	mkdir -p "$dir"
	for label in "$@"; do
		IFS='|' read -r binary setup variant <<<"$(config "$label")"
		local file=$queries/$query.$variant.sql
		[ -f "$file" ] || { log "  $query $label: no $file, skipped"; continue; }
		log "profile $(basename "$dir") $query $label"
		THREADS=1 SETUP="$setup" LABEL="$query,$label" python3 "$HERE/profile_stacks.py" "$binary" "$DATA" "$file" \
			"$dir/$query.$label" >/dev/null 2>"$dir/$query.$label.err" || log "  failed: $(tail -1 "$dir/$query.$label.err")"
		[ -s "$dir/$query.$label.err" ] || rm -f "$dir/$query.$label.err"
	done
}

Q2C="q2_c01 q2_c10 q2_c25 q2_c50 q2_c75"
for step in $STEPS; do
	log "step $step"
	case $step in
	check)
		{
			echo "date:     $(date -Iseconds)"
			echo "host:     $(hostname), $(lscpu | sed -n 's/^Model name: *//p'), kernel $(uname -r)"
			echo "uptime:   $(uptime)"
			echo "scripts:  $(git -C "$HERE" log -1 --format='%h %s' 2>/dev/null)"
			echo "perf:     $($PERF version 2>&1)"
			echo "time:     $(command -v /usr/bin/time || echo 'no /usr/bin/time')"
			echo "--- metric groups with Topdown:"
			$PERF list metricgroups 2>/dev/null | grep -i topdown | head -10
			echo "--- $PERF stat -M $TOPDOWN -e cycles,branch-misses -- $BASE -c 'SELECT sum(range) FROM range(100000000)':"
			$PERF stat -M "$TOPDOWN" -e cycles,branch-misses -- "$BASE" -no-agent -c "SELECT sum(range) FROM range(100000000)" 2>&1 | tail -20
		} 2>&1 | tee "$OUT/check.txt"
		;;
	g2)
		for q in q4_two.orig q4_two.small_build; do
			profile "$OUT/profile/g2" "$HERE/queries_build" "$q" base prenest
		done
		EVENTS=page-faults,minor-faults,major-faults,task-clock,cycles MAXRSS=1 THREADS=1 CONFIGS="base prenest" \
			python3 "$HERE/perf_stat.py" "$HERE/queries_build" "$DATA" "$OUT/g2_stat.csv" q4_two.orig q4_two.small_build \
			| tee "$OUT/g2_stat.log"
		;;
	g1)
		# TOPDOWN=raw: the events of the level-1 Bad Speculation formula instead of perf's metric group
		if [ "$TOPDOWN" = raw ]; then
			selection="EVENTS=cycles,task-clock,uops_issued.any,uops_retired.retire_slots,int_misc.recovery_cycles METRICS="
		else
			selection="EVENTS=cycles,task-clock METRICS=$TOPDOWN"
		fi
		# shellcheck disable=SC2086
		env $selection THREADS=1 python3 "$HERE/perf_stat.py" "$TRADE/queries" "$DATA" \
			"$OUT/g1_topdown.csv" $Q2C | tee "$OUT/g1_topdown.log"
		# shellcheck disable=SC2086
		EVENTS=cycles,task-clock,branches,branch-misses THREADS=1 python3 "$HERE/perf_stat.py" "$TRADE/queries" "$DATA" \
			"$OUT/g1_branches.csv" $Q2C | tee "$OUT/g1_branches.log"
		if [ ! -f "$DATA/trade_Bsorted.parquet" ]; then
			log "writing trade_Bsorted.parquet"
			/usr/bin/time -v "$PY" -I "$TRADE/write_trade.py" --sort-legs "$DATA/trade_B.parquet" "$DATA/trade_Bsorted.parquet" \
				>"$OUT/g1_sorted_write.txt" 2>&1 || { log "writing trade_Bsorted failed, see g1_sorted_write.txt"; continue; }
		fi
		python3 "$HERE/verify_narrow.py" "$DATA" trade_Bsorted.parquet --reordered | tee "$OUT/g1_sorted_verify.md"
		if grep -q '| NO' "$OUT/g1_sorted_verify.md"; then log "WARNING: trade_Bsorted differs from trade_B, see g1_sorted_verify.md"; fi
		RUNS=$RUNS THREADS=1 CONFIGS="base prenestoff prenest flat" python3 "$HERE/time_queries.py" "$HERE/queries_sorted" \
			"$DATA" "$OUT/g1_sorted_time.csv" | tee "$OUT/g1_sorted_time.log"
		for q in q2_c50.orig q2_c50.sorted; do
			profile "$OUT/profile/g1sorted" "$HERE/queries_sorted" "$q" base prenestoff prenest flat
		done
		EVENTS=cycles,task-clock,branches,branch-misses THREADS=1 python3 "$HERE/perf_stat.py" "$HERE/queries_sorted" \
			"$DATA" "$OUT/g1_sorted_branches.csv" q2_c50.orig q2_c50.sorted | tee "$OUT/g1_sorted_branches.log"
		;;
	g3)
		if [ ! -f "$DATA/../fanout/fanout.duckdb" ]; then
			FACT=1 python3 "$HERE/make_fanout.py" "$DATA" | tee "$OUT/g3_fanout_data.md"
		fi
		for q in a_k04.preagg c_k04.preagg; do
			profile "$OUT/profile/g3" "$HERE/queries_fanout" "$q" base prenest
		done
		RUNS=$RUNS THREADS=1 CONFIGS="base prenestoff prenest" python3 "$HERE/time_queries.py" "$HERE/queries_stage" \
			"$DATA" "$OUT/g3_stage_parquet.csv" s1_box s2_unnest s3_cond | tee "$OUT/g3_stage_parquet.log"
		RUNS=$RUNS THREADS=1 CONFIGS="base prenestoff prenest" python3 "$HERE/time_queries.py" "$HERE/queries_stage_db" \
			"$DATA" "$OUT/g3_stage_db.csv" | tee "$OUT/g3_stage_db.log"
		;;
	g4)
		LISTS=${SYN_LISTS:-100000000} python3 "$HERE/make_syn.py" "$DATA" | tee "$OUT/g4_files.md"
		RUNS=$RUNS THREADS=1 CONFIGS="base prenestoff flat" python3 "$HERE/time_queries.py" "$HERE/queries_syn" \
			"$DATA" "$OUT/g4_time.csv" | tee "$OUT/g4_time.log"
		for q in syn_L01 syn_L02 syn_L04 syn_L08 syn_L16 syn_L32; do
			profile "$OUT/profile/g4" "$HERE/queries_syn" "$q" base prenestoff flat
		done
		;;
	summary)
		python3 "$HERE/summarize_g.py" "$OUT" >"$OUT/summary.md" && log "summary: $OUT/summary.md"
		;;
	*)
		log "unknown step $step"; exit 2 ;;
	esac
done
log "done: $OUT"
