#!/usr/bin/env bash
# Make every Parquet file of the trade experiment from the original archives (README.md, step 2):
#   <out>/full/      trade_A.parquet, trade_B.parquet, trade_C.parquet, pureflat/{parent,c11,c12,c13,c14,legs}.parquet - the 100M rows
#   <out>/distinct/  the same files with every distinct row once (249,728 rows)
#   <out>/dims/      csa_dictionary.parquet, date_plots.parquet (dates as a list), date_plots_flat.parquet
# then checks them (verify_trade.sh).
#
# The rows are shuffled reproducibly: the distinct rows of the CSV are counted, and every copy (distinct row, k-th copy)
# gets the position hash(row, k, SEED). The distinct version keeps the distinct rows in the order hash(row, SEED).
#
# Usage: prepare_trade.sh <tradeFactTable-001.zip | factTableFormatted.csv> <Data-...zip | folder with the two dim CSVs>
#                         [--out <folder>] [--distinct-only]
#   --distinct-only  only the distinct version and the dims (reads the whole CSV once, writes no 100M-row file)
# Environment: DUCKDB (default: the base build of README.md), PY (python with pyarrow 26.0.0), SEED (20261028),
#              KEEP_WORK=1 keeps <out>/work (the extracted CSV and the intermediate files).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
NB=${NB:-$HOME/nested-bench}
DUCKDB=${DUCKDB:-$NB/duckdb_base/build/release/duckdb}
PY=${PY:-$NB/venv/bin/python}
SEED=${SEED:-20261028}
OUT=$HERE/data DISTINCT_ONLY=0 ARGS=()
while [ $# -gt 0 ]; do
	case "$1" in
	--out) OUT=$2; shift 2 ;;
	--distinct-only) DISTINCT_ONLY=1; shift ;;
	*) ARGS+=("$1"); shift ;;
	esac
done
if [ ${#ARGS[@]} -ne 2 ]; then
	sed -n '2,17p' "$0"
	exit 2
fi
FACT=$(realpath "${ARGS[0]}") DIMS=$(realpath "${ARGS[1]}")
VERSION=$("$PY" -c "import pyarrow; print(pyarrow.__version__)" 2>/dev/null || echo "none")
if [ "$VERSION" != "26.0.0" ]; then
	echo "ERROR: $PY has pyarrow $VERSION, 26.0.0 is needed (README.md, step 1)"
	exit 1
fi
[ -x "$DUCKDB" ] || { echo "ERROR: no DuckDB binary at $DUCKDB"; exit 1; }
mkdir -p "$OUT" && OUT=$(cd "$OUT" && pwd)
WORK=$OUT/work
mkdir -p "$WORK/duckdb_tmp" "$WORK/raw"
log() { echo "[$(date +%T)] $*"; }
log "duckdb: $("$DUCKDB" -no-agent -noheader -list -c "SELECT library_version || ' ' || source_id FROM pragma_version()")"
log "pyarrow $VERSION, seed $SEED, out $OUT"

# 1. Extract (Python, so that unzip is not needed; the dims archive holds one zip per table)
"$PY" -I - "$FACT" "$DIMS" "$WORK/raw" <<-'PYEOF'
	import io, os, shutil, sys, zipfile
	fact, dims, raw = sys.argv[1:4]
	def extract(source, name, target):
	    path = os.path.join(raw, target)
	    if os.path.exists(path):
	        return
	    with source.open(name) as src, open(path + ".partial", "wb") as dst:
	        shutil.copyfileobj(src, dst, 1 << 24)
	    os.replace(path + ".partial", path)
	if fact.endswith(".zip"):
	    extract(zipfile.ZipFile(fact), "factTableFormatted.csv", "fact.csv")
	elif not os.path.exists(os.path.join(raw, "fact.csv")):
	    os.symlink(fact, os.path.join(raw, "fact.csv"))
	for table in ("csaDictionaryJoin", "datePlotsZipTable"):
	    if dims.endswith(".zip"):
	        outer = zipfile.ZipFile(dims)
	        inner = zipfile.ZipFile(io.BytesIO(outer.read(f"Data/{table}.zip")))
	        extract(inner, f"{table}.csv", f"{table}.csv")
	    else:
	        shutil.copy(os.path.join(dims, f"{table}.csv"), os.path.join(raw, f"{table}.csv"))
PYEOF
log "extracted: $(ls -lL "$WORK/raw" | awk 'NR > 1 {print $NF " " $5}' | tr '\n' ' ')"

COLS=$(seq -s, -f 'c%g' 0 22)
CSV_COLUMNS=$(seq -s, -f "c%g: 'VARCHAR'" 0 22)
duck() { "$DUCKDB" -no-agent "${@:2}" -c "SET temp_directory = '$WORK/duckdb_tmp'; SET preserve_insertion_order = true;" -c "$1"; }

# 2. Distinct rows with their count, typed, in the order hash(row, SEED)
if [ ! -f "$WORK/distinct.parquet" ]; then
	log "distinct rows of the CSV"
	duck "
	CREATE TABLE raw AS
	SELECT *, count(*) AS n
	FROM read_csv('$WORK/raw/fact.csv', header = false, delim = ',', quote = '\"', escape = '\"', columns = {$CSV_COLUMNS})
	GROUP BY ALL;
	COPY (
		SELECT row_number() OVER (ORDER BY hash($COLS, $SEED::BIGINT), $COLS) - 1 AS idx, n, hash($COLS) AS h,
		       c0::DATE AS c0, c1::UBIGINT AS c1, c2::DATE AS c2, c3, c4, c5, c6, c7, c8, c9::BIGINT AS c9,
		       c10::BIGINT AS c10, c11::BIGINT[] AS c11, c12::BIGINT[] AS c12, c13::BIGINT[] AS c13,
		       c14::VARCHAR[] AS c14, c15::VARCHAR[] AS c15, c16::VARCHAR[] AS c16, c17::VARCHAR[] AS c17,
		       c18::BIGINT[] AS c18, c19::INTEGER AS c19, c20::INTEGER AS c20, c21::INTEGER AS c21, c22::INTEGER AS c22
		FROM raw ORDER BY idx
	) TO '$WORK/distinct.parquet.partial' (FORMAT parquet);" >/dev/null
	mv "$WORK/distinct.parquet.partial" "$WORK/distinct.parquet"
fi
log "distinct: $(duck "SELECT count(*) || ' rows, ' || sum(n) || ' with copies' FROM '$WORK/distinct.parquet'" -noheader -list | tail -1)"

# 3. Dimension tables
duck "
COPY (SELECT * FROM read_csv('$WORK/raw/csaDictionaryJoin.csv', header = false,
                             columns = {csa: 'VARCHAR', as_of_date: 'DATE', csa_hash: 'UBIGINT'}))
	TO '$WORK/csa_dictionary.parquet' (FORMAT parquet);
COPY (SELECT reg_scenario, plot_dates::DATE[] AS plot_dates
      FROM read_csv('$WORK/raw/datePlotsZipTable.csv', header = false, quote = '\"',
                    columns = {reg_scenario: 'VARCHAR', plot_dates: 'VARCHAR'}))
	TO '$WORK/date_plots.parquet' (FORMAT parquet);
COPY (SELECT reg_scenario, unnest(plot_dates) AS plot_date FROM '$WORK/date_plots.parquet')
	TO '$WORK/date_plots_flat.parquet' (FORMAT parquet);" >/dev/null
for table in csa_dictionary date_plots date_plots_flat; do
	"$PY" -I "$HERE/write_trade.py" --rewrite "$WORK/$table.parquet" "$OUT/dims/$table.parquet"
done

# 4. The distinct version: A, B, C and pure flat in parallel
write_all() { # <order.parquet | -> <out folder>
	local pids=() part
	for part in A B C flat; do
		"$PY" -I "$HERE/write_trade.py" "$WORK/distinct.parquet" "$1" "$2" $part &
		pids+=($!)
	done
	for pid in "${pids[@]}"; do wait "$pid"; done
}
log "writing $OUT/distinct"
write_all - "$OUT/distinct"

# 5. The full version: the shuffled order of the 100M copies, then A, B, C and pure flat in parallel
if [ $DISTINCT_ONLY = 0 ]; then
	if [ ! -f "$WORK/order.parquet" ]; then
		log "shuffled order of all rows"
		duck "
		COPY (SELECT idx::INTEGER AS idx
		      FROM (SELECT idx, h, unnest(range(n)) AS k FROM '$WORK/distinct.parquet')
		      ORDER BY hash(h, k, $SEED::BIGINT), idx, k)
			TO '$WORK/order.parquet.partial' (FORMAT parquet);" >/dev/null
		mv "$WORK/order.parquet.partial" "$WORK/order.parquet"
	fi
	log "writing $OUT/full"
	write_all "$WORK/order.parquet" "$OUT/full"
fi

log "checking"
DUCKDB=$DUCKDB PY=$PY "$HERE/verify_trade.sh" "$OUT" | tee "$OUT/verify.txt"
[ "${KEEP_WORK:-0}" = 1 ] || rm -rf "$WORK"
log "done"
