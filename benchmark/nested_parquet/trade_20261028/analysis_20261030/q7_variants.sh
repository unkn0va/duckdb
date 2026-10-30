#!/usr/bin/env bash
# q7_plots at 1 thread: the original query of each configuration and two rewrites, the fixed join order
# (*_reorder: legs ⋈ parent first, then the dim) and the aggregation before the dim join (*_preagg: by c8 first).
# Prints the fastest of RUNS and a hash of the result; with PLANS=1 also the plan (plan_tree.py: build/probe,
# estimated and actual rows per operator).
#
# Usage: q7_variants.sh <data folder: trade_B.parquet, pureflat/, and the dims in ../dims/> [RUNS, default 5]
# Environment: BASE, FINAL (the binaries of ../run_trade.sh), PLANS
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DATA=$(cd "$1" && pwd)
RUNS=${2:-5}
NB=${NB:-$HOME/nested-bench}
BASE=${BASE:-$NB/duckdb_base/build/release/duckdb}
FINAL=${FINAL:-$NB/duckdb_rey/build/release/duckdb}

for v in builtin:$BASE builtin_preagg:$BASE flat:$FINAL flat_reorder:$FINAL flat_preagg:$FINAL \
	split:$BASE split_reorder:$BASE split_preagg:$BASE; do
	name=${v%%:*} binary=${v#*:}
	# the SET of a rewrite runs before the timer, so that its own time is not taken as the fastest run
	setup="SET threads = 1; $(grep '^SET' "$HERE/q7/$name.sql" || true)"
	sql=$(grep -v '^SET' "$HERE/q7/$name.sql")
	result=$(cd "$DATA" && "$binary" -no-agent -csv -noheader -c "$setup" -c "$sql" | md5sum | cut -c1-8)
	best=$(cd "$DATA" && {
		echo "$setup"
		echo ".timer on"
		echo ".mode trash"
		for _ in $(seq "$RUNS"); do echo "$sql"; done
	} | "$binary" -no-agent 2>&1 | grep -o 'real [0-9.]*' | awk '{print $2}' | sort -n | head -1)
	printf '%-16s %8s s  result %s\n' "$name" "$best" "$result"
	if [ -n "${PLANS:-}" ]; then
		SETUP="$setup" python3 "$HERE/plan_tree.py" "$binary" "$DATA" "$sql" | sed 's/^/    /'
	fi
done
