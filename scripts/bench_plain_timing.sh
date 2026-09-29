#!/bin/bash
# Same method as bench_prenest_timing.sh, for binaries without parquet_prenest_auto:
# fresh process per run, 6 runs, first discarded, median of 5, /usr/bin/time -f %e.
BIN=${BIN:?set BIN}
Q=${Q:-/choily/tpch-queries}
ls $Q/q*.sql >/dev/null 2>&1 || { echo "no queries in $Q" >&2; exit 1; }
echo -e "query\ttime"
for f in $Q/q*.sql; do
  q=$(basename $f .sql); ts=()
  for i in $(seq 0 5); do
    t=$( { /usr/bin/time -f %e "$BIN" -noheader -list -c "$(cat $f);" >/dev/null; } 2>&1 )
    [ $i -gt 0 ] && ts+=($t)
  done
  echo -e "$q\t$(printf "%s\n" "${ts[@]}" | sort -n | sed -n 3p)"
done
