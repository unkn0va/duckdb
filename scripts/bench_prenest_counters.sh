#!/usr/bin/env bash
# Per-query prenest element counters, as committed under results/<date>/duckdb_counters.tsv.
#
# One run per query with parquet_prenest_auto=true. The counters are exact, so there
# is nothing to take a median of, and auto=false is not a second column here - the
# reader only counts when a spec reaches it, so with the pass off there is nothing to
# count. Wall-clock off-vs-on is the separate duckdb_mt.tsv.
#
# Both counters are the SUM over all specs in a scan; per-list values come from
# parquet_prenest_stat('elements_appended:<list>').
#
# Emits one row per query: <query>\t<elements_decoded> <elements_appended>
#
#   scripts/bench_prenest_counters.sh > results/$(date +%F)/duckdb_counters.tsv
#
# BIN and QDIR override the binary and the query directory.

set -euo pipefail

BIN=${BIN:-./build/release/duckdb}
QDIR=${QDIR:-$HOME/nested_queries}

printf 'query\tdecoded appended\n'
for f in "$QDIR"/q*.sql; do
	q=$(basename "$f" .sql)
	# reset, run, read: three statements, so the counters are the LAST line out.
	printf '%s\t%s\n' "$q" "$(
		"$BIN" -noheader -list -c "
  SELECT parquet_prenest_stat('reset');
  SET parquet_prenest_auto=true;
  $(cat "$f");
  SELECT parquet_prenest_stat('elements_decoded')||' '||parquet_prenest_stat('elements_appended');" | tail -1
	)"
done
