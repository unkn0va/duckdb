#!/usr/bin/env bash
# Follow-up checks on the 2026-10-26 three-binary run (server_20261026_3way_base/summary.md). Run on the server, in
# tmux; every step writes to its own folder under --out and can be run alone.
#
#   meta     row groups, top-level rows and writer of every dataset file (parquet_metadata), a few seconds
#   rewrite  rewrite SF1, XMark and the selectivity files with pyarrow twice: one row group (rg1, the control) and
#            ceil(rows / 20) rows per row group (rg20); files with a single top-level row cannot be split, minutes
#   rg       base / prenest / prenestoff / flat on rg1 and rg20 at 1 and 20 threads: rg1 vs rg20 is the effect of
#            parallelism alone, since both went through the same writer
#   off      all datasets, original data, 1 and 20 threads, with prenest-3way at parquet_prenest_auto = false
#            as well (run_all.sh --prenest-off): is prenestoff equal to base? Times and results are both checked
#   counters TPC-H SF1 q01 with prenest-3way: decoded / appended elements and the optimizer counters at auto =
#            true and false, the share of lineitems that pass the filter, and EXPLAIN ANALYZE for both
#   explain  Selectivity (B): EXPLAIN and EXPLAIN ANALYZE of every flat query (main_rey, query settings) at 1 and
#            20 threads, and of the builtin n3 for comparison
#   split    not in the default steps; needs rewrite. Why flat is slower on TPC-H SF1 rg20 at 20 threads: the
#            read_parquet_node debug log (parts per row group, split at or within pages, page counts, level counting)
#            of every flat query on the original file, rg1 and rg20, and the flat queries at 20 threads with fewer
#            parts (parquet_node_task_slots x2, x4) and without splitting the scans that count levels
#            (parquet_node_physical_cores = 1)
#
# Usage: followup_checks.sh [--steps "meta rewrite rg off counters explain"] [--out <folder>] [--runs 10]
#        Paths default to SERVER.md's layout under ~/nested-bench; override with NB, BASE, FINAL, PRENEST, DATA, PY.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
NB=${NB:-$HOME/nested-bench}
BASE=${BASE:-$NB/duckdb_base/build/release/duckdb}
FINAL=${FINAL:-$NB/duckdb_rey/build/release/duckdb}
PRENEST=${PRENEST:-$NB/duckdb_prenest_base/build/release/duckdb}
DATA=${DATA:-$NB/data}
PY=${PY:-$NB/venv/bin/python}
STEPS="meta rewrite rg off counters explain" OUT="" RUNS=10
while [ $# -gt 0 ]; do
	case "$1" in
	--steps) STEPS=$2; shift 2 ;;
	--out) OUT=$2; shift 2 ;;
	--runs) RUNS=$2; shift 2 ;;
	*) sed -n '2,20p' "$0"; exit 2 ;;
	esac
done
OUT=${OUT:-$HERE/followup_$(date +%Y%m%d_%H%M)}
mkdir -p "$OUT"
for binary in "$BASE" "$FINAL" "$PRENEST"; do
	[ -x "$binary" ] || { echo "ERROR: $binary is not an executable file"; exit 1; }
done

QUERY_SETUP="SET disabled_optimizers = 'join_filter_pushdown';SET parquet_node_join_filter_pruning = false"
# dataset, folder in the data folder, file the queries read
FILES="tpch_sf1 nested-parquet-datasets/nested-tpch nestedregion.parquet
tpch_sf10 nested-parquet-datasets/nested-tpch-sf10 nestedcustomer.parquet
xmark nested-parquet-datasets/xmark sf10.parquet
dblp nested-parquet-datasets/dblp dblp.parquet
selectivity_random selectivity_random l1.parquet
selectivity_sorted selectivity_sorted l1.parquet"
REWRITE="tpch_sf1 xmark selectivity_random selectivity_sorted"

# -no-agent only for the shells that know it (prenest-3way is older)
duck() {
	local bin=$1
	shift
	if "$bin" -no-agent -c "SELECT 1" >/dev/null 2>&1; then
		"$bin" -no-agent "$@"
	else
		"$bin" "$@"
	fi
}

step_meta() {
	local f="$OUT/meta.tsv"
	printf 'layout\tdataset\tfile\trow_groups\ttop_level_rows\tmax_rows_per_row_group\tcompression\tcreated_by\n' >"$f"
	local layout dataset dir file root
	for layout in orig rg1 rg20; do
		case $layout in
		orig) root=$DATA ;;
		*) root=$NB/data_$layout ;;
		esac
		while read -r dataset dir file; do
			[ -f "$root/$dir/$file" ] || continue
			(cd "$root/$dir" && duck "$BASE" -noheader -csv -separator $'\t' -c "
				SELECT '$layout', '$dataset', '$file', count(DISTINCT row_group_id),
				       (SELECT num_rows FROM parquet_file_metadata('$file')), max(row_group_num_rows),
				       string_agg(DISTINCT compression, ','), (SELECT created_by FROM parquet_file_metadata('$file'))
				FROM parquet_metadata('$file')") >>"$f"
		done <<<"$FILES"
	done
	column -t -s $'\t' "$f"
}

step_rewrite() {
	local dataset dir file
	for dataset in $REWRITE; do
		read -r _ dir file < <(grep "^$dataset " <<<"$FILES")
		"$PY" -I - "$DATA/$dir/$file" "$NB/data_rg1/$dir/$file" "$NB/data_rg20/$dir/$file" <<-'PYEOF' | tee -a "$OUT/rewrite.txt"
			import math, os, sys
			import pyarrow.parquet as pq
			src, rg1, rg20 = sys.argv[1:]
			meta = pq.ParquetFile(src).metadata
			codec = meta.row_group(0).column(0).compression.lower().replace("uncompressed", "none")
			table = pq.read_table(src)
			rows = table.num_rows
			for path, per_group in ((rg1, rows), (rg20, math.ceil(rows / 20))):
			    if path == rg20 and rows < 2:
			        print(f"{src}: {rows} top-level row, cannot be split into row groups - rg20 skipped")
			        continue
			    os.makedirs(os.path.dirname(path), exist_ok=True)
			    pq.write_table(table, path, row_group_size=per_group, compression=codec)
			    groups = pq.ParquetFile(path).metadata.num_row_groups
			    print(f"{path}: {rows} rows, {groups} row groups, {codec}")
		PYEOF
	done
	step_meta >/dev/null
}

# base, prenest (auto on), prenestoff (auto off) on the builtin queries, final on the flat ones
bench() { # <dataset> <data dir> <threads> <out csv>
	local binaries="base=$BASE,prenest=$PRENEST;SET parquet_prenest_auto = true"
	binaries="$binaries,prenestoff=$PRENEST;SET parquet_prenest_auto = false,final=$FINAL"
	[[ $1 == selectivity_* ]] && binaries="$binaries;$QUERY_SETUP"
	RUNS=$RUNS THREADS=$3 VARIANTS="base=builtin final=flat,flat_minmax prenest=builtin prenestoff=builtin" \
		python3 "$HERE/run_bench.py" "$binaries" "$HERE/queries/$1" "$2" "$4"
}

step_rg() {
	local layout dataset dir file
	for layout in rg1 rg20; do
		mkdir -p "$OUT/$layout/logs"
		for dataset in $REWRITE; do
			read -r _ dir file < <(grep "^$dataset " <<<"$FILES")
			[ -f "$NB/data_$layout/$dir/$file" ] || { echo "== $layout $dataset: no rewritten file, skipped"; continue; }
			echo "== $layout $dataset: started $(date +%H:%M)"
			bench "$dataset" "$NB/data_$layout/$dir" 1,20 "$OUT/$layout/$dataset.csv" >"$OUT/$layout/logs/$dataset.log" 2>&1 ||
				{ echo "ERROR: see $OUT/$layout/logs/$dataset.log"; tail -5 "$OUT/$layout/logs/$dataset.log"; }
		done
		python3 "$HERE/summarize.py" "$OUT/$layout" >"$OUT/$layout/summary.md"
		python3 "$HERE/check_results.py" "$OUT/$layout" | tee "$OUT/$layout/result_check.txt"
	done
	echo "rg1 vs rg20: $OUT/rg1/summary.md, $OUT/rg20/summary.md"
}

step_off() {
	"$HERE/run_all.sh" --base "$BASE" --final "$FINAL" --data "$DATA" --prenest "$PRENEST" --prenest-off \
		--threads "1 20" --runs "$RUNS" --out "$OUT/off"
}

step_counters() {
	local f="$OUT/q01_counters.txt" q auto
	q=$(cat "$HERE/queries/tpch_sf1/q01.builtin.sql")
	cd "$DATA/nested-parquet-datasets/nested-tpch" || return 1
	{
		echo "## lineitems in total and passing l_shipdate <= date '1998-12-01' - interval '90' day (base)"
		duck "$BASE" -c "SELECT count(*) AS lineitems,
			count(*) FILTER (WHERE l_shipdate <= date '1998-12-01' - interval '90' day) AS passing,
			round(passing / lineitems, 4) AS share
			FROM (SELECT unnest(o_lineitems, recursive := true) FROM (SELECT unnest(c_orders, recursive := true)
			FROM (SELECT unnest(n_customers, recursive := true) FROM (SELECT unnest(r_nations, recursive := true)
			FROM 'nestedregion.parquet'))))"
		for auto in true false; do
			echo
			echo "## prenest-3way, parquet_prenest_auto = $auto"
			duck "$PRENEST" -c "SET parquet_prenest_auto = $auto" -c "SELECT parquet_prenest_stat('reset')" \
				-c ".timer on" -c "$q" -c ".timer off" -c "
				SELECT parquet_prenest_stat('elements_decoded') AS elements_decoded,
				       parquet_prenest_stat('elements_appended') AS elements_appended,
				       parquet_prenest_stat('predicate_elements') AS predicate_elements,
				       parquet_prenest_stat('inner_iterations') AS inner_iterations,
				       parquet_prenest_stat('carryovers') AS carryovers,
				       parquet_prenest_stat('carryover_flattens') AS carryover_flattens" -c "
				SELECT path, parquet_prenest_stat('elements_appended:' || list) AS elements_appended,
				       parquet_prenest_stat('predicate_elements:' || list) AS predicate_elements
				FROM (SELECT path, regexp_extract(path, '([^.\[\]]+)$', 1) AS list
				      FROM (SELECT unnest(string_split(parquet_prenest_lists(), ',')) AS path) WHERE path <> '')" -c "
				SELECT name, parquet_prenest_stat('opt:' || name) AS value
				FROM (SELECT unnest(['comprehensions_formed', 'binders_not_formable', 'passthroughs',
				      'levels_lifted', 'absorbed_at_scan', 'specs_pushed', 'rolled_up',
				      'refused_list_read_elsewhere', 'dropped']) AS name)"
		done
		for auto in true false; do
			echo
			echo "## EXPLAIN ANALYZE, threads = 1, parquet_prenest_auto = $auto"
			duck "$PRENEST" -c "SET threads = 1" -c "SET parquet_prenest_auto = $auto" -c "EXPLAIN ANALYZE $q"
		done
		echo
		echo "## EXPLAIN ANALYZE, threads = 1, base"
		duck "$BASE" -c "SET threads = 1" -c "EXPLAIN ANALYZE $q"
	} 2>&1 | tee "$f"
	cd - >/dev/null
}

step_explain() {
	local d="$OUT/explain_selectivity_sorted" n threads setup
	mkdir -p "$d"
	cd "$DATA/selectivity_sorted" || return 1
	setup=(-c "SET disabled_optimizers = 'join_filter_pushdown'" -c "SET parquet_node_join_filter_pruning = false")
	for n in 0 1 2 3 4 5 6; do
		for threads in 1 20; do
			{
				cat "$HERE/queries/selectivity_sorted/n$n.flat.sql"
				echo
				duck "$FINAL" -c "SET threads = $threads" "${setup[@]}" \
					-c "EXPLAIN $(cat "$HERE/queries/selectivity_sorted/n$n.flat.sql")" \
					-c "EXPLAIN ANALYZE $(cat "$HERE/queries/selectivity_sorted/n$n.flat.sql")"
				echo "## wall clock of the CLI process (startup + catalog + query)"
				/usr/bin/time -f "%e s" "$FINAL" -no-agent -c "SET threads = $threads" "${setup[@]}" \
					-c "$(cat "$HERE/queries/selectivity_sorted/n$n.flat.sql")" >/dev/null
				/usr/bin/time -f "%e s (SELECT 1 only)" "$FINAL" -no-agent -c "SELECT 1" >/dev/null
			} >"$d/n${n}_flat_t$threads.txt" 2>&1
		done
	done
	for threads in 1 20; do
		duck "$BASE" -c "SET threads = $threads" -c "EXPLAIN ANALYZE $(cat "$HERE/queries/selectivity_sorted/n3.builtin.sql")" \
			>"$d/n3_builtin_t$threads.txt" 2>&1
	done
	cd - >/dev/null
	grep -H "Total Time" "$d"/*.txt
	echo "plans: $d"
}

step_split() {
	local d="$OUT/split" layout root q dir=nested-parquet-datasets/nested-tpch
	mkdir -p "$d"
	for layout in orig rg1 rg20; do
		case $layout in
		orig) root=$DATA ;;
		*) root=$NB/data_$layout ;;
		esac
		[ -f "$root/$dir/nestedregion.parquet" ] || { echo "== $layout: no file, skipped (run the rewrite step)"; continue; }
		echo "== $layout: started $(date +%H:%M)"
		for q in "$HERE"/queries/tpch_sf1/q*.flat.sql; do
			(cd "$root/$dir" && duck "$FINAL" -list -noheader -c "SET threads = 20" \
				-c "CALL enable_logging(level := 'debug', storage := 'memory')" -c "$(cat "$q")" \
				-c "SELECT message FROM duckdb_logs WHERE message LIKE 'read_parquet_node:%'") \
				>"$d/${layout}_$(basename "$q" .flat.sql)_log.txt" 2>&1
		done
		RUNS=$RUNS THREADS=20 VARIANTS="default=flat slots2x=flat slots4x=flat nosplit=flat" \
			python3 "$HERE/run_bench.py" \
			"default=$FINAL,slots2x=$FINAL;SET parquet_node_task_slots = 245760,slots4x=$FINAL;SET parquet_node_task_slots = 491520,nosplit=$FINAL;SET parquet_node_physical_cores = 1" \
			"$HERE/queries/tpch_sf1" "$root/$dir" "$d/$layout.csv" >"$d/$layout.log" 2>&1 ||
			{ echo "ERROR: see $d/$layout.log"; tail -5 "$d/$layout.log"; }
	done
	python3 - "$d" <<-'PYEOF' | tee "$d/table.md"
		import csv, os, sys
		d = sys.argv[1]
		labels = ["default", "slots2x", "slots4x", "nosplit"]
		print("flat at 20 threads, seconds (CPU seconds); default task slots = 122880, slots2x = 245760, slots4x = 491520,")
		print("nosplit = parquet_node_physical_cores = 1 (scans that count levels are not split)\n")
		print("| layout | query | " + " | ".join(labels) + " |")
		print("|---|---|" + "---|" * len(labels))
		for layout in ("orig", "rg1", "rg20"):
		    path = os.path.join(d, layout + ".csv")
		    if not os.path.exists(path):
		        continue
		    for row in csv.DictReader(open(path)):
		        cells = [f"{row.get(f'flat_{l}_s', '?')} ({row.get(f'flat_{l}_cpu', '?')})" for l in labels]
		        print(f"| {layout} | {row['query']} | " + " | ".join(cells) + " |")
	PYEOF
	echo
	echo "parts per row group (default settings):"
	grep -H "is scanned in\|are split\|are not split" "$d"/*_log.txt | sed "s#$d/##" | cut -c1-260 ||
		echo "(no read_parquet_node messages - see $d/*_log.txt)"
}

{
	echo "date:     $(date -Is)"
	echo "host:     $(hostname), $(nproc) hardware threads"
	for b in BASE PRENEST FINAL; do
		printf '%-9s %s  %s\n' "${b,,}:" "$(duck "${!b}" -csv -noheader -c "SELECT concat_ws(' ', library_version, source_id) FROM pragma_version()")" "${!b}"
	done
	echo "steps:    $STEPS, runs: $RUNS"
} | tee -a "$OUT/run_info.txt"

for step in $STEPS; do
	echo
	echo "#### $step ($(date +%H:%M))"
	"step_$step" || echo "ERROR: step $step failed"
done
echo
echo "Results: $OUT"
