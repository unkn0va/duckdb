#!/bin/bash
# Timing for results/<date>/duckdb_mt.tsv. Same method as results/2026-09-17 and 2026-09-19:
# one fresh duckdb process per run, 6 runs per (query, mode), first discarded,
# median of the remaining 5 (3rd after sort), wall clock via /usr/bin/time -f %e,
# process startup included, default parallelism.
BIN=${BIN:-./build/release/duckdb}
Q=${Q:-/choily/tpch-queries}
echo -e "query\toff\ton\tratio"
for f in $Q/q*.sql; do
  q=$(basename $f .sql)
  for mode in false true; do
    ts=()
    for i in $(seq 0 5); do
      t=$( { /usr/bin/time -f %e "$BIN" -noheader -list -c \
             "SET parquet_prenest_auto=$mode; $(cat $f);" >/dev/null; } 2>&1 )
      [ $i -gt 0 ] && ts+=($t)
    done
    m=$(printf "%s\n" "${ts[@]}" | sort -n | sed -n 3p)
    [ $mode = false ] && off=$m || on=$m
  done
  echo -e "$q\t$off\t$on\t$(echo "scale=3; $off/$on" | bc)"
done
