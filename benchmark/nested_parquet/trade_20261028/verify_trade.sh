#!/usr/bin/env bash
# Check the files of prepare_trade.sh against the CSV and against each other, for <out>/distinct and <out>/full:
#   lengths  rows, elements and longest list of c11..c14 and of legs (c15..c18), and the rows whose four leg lists have
#            the same length - from the CSV (by counting commas), A, B, C and pure flat; "same" = all sources agree.
#            The distinct version is compared with the distinct rows of the CSV.
#   content  A = B and C = B row by row (positional), parent = B's scalars with sk = row number, every pure flat list table =
#            B's list unnested (sum of hash(sk, element)), every parent has elements in every list table; for full
#            and distinct both present: their sets of distinct rows are equal
#   pages    row groups, data pages per row group per column, sizes (page_counts.py)
#
# Usage: verify_trade.sh <out folder of prepare_trade.sh>   (the CSV is read from <out>/work/raw/fact.csv)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
NB=${NB:-$HOME/nested-bench}
DUCKDB=${DUCKDB:-$NB/duckdb_base/build/release/duckdb}
PY=${PY:-$NB/venv/bin/python}
OUT=$(cd "$1" && pwd)
CSV=$OUT/work/raw/fact.csv
CSV_COLUMNS=$(seq -s, -f "c%g: 'VARCHAR'" 0 22)
SCALARS=$(seq -s, -f 'c%g' 0 10),c19,c20,c21,c22
duck() { "$DUCKDB" -no-agent -markdown -c "SET temp_directory = '$OUT/work/duckdb_tmp';" -c "$1"; }

lengths_csv() { # <relation> <label>
	echo "SELECT '$2' AS source, count(*) AS rows,
		sum(n(c11)) AS c11_elements, max(n(c11)) AS c11_max, sum(n(c12)) AS c12_elements, max(n(c12)) AS c12_max,
		sum(n(c13)) AS c13_elements, max(n(c13)) AS c13_max, sum(n(c14)) AS c14_elements, max(n(c14)) AS c14_max,
		sum(n(c15)) AS legs_elements, max(n(c15)) AS legs_max,
		count(*) FILTER (n(c15) = n(c16) AND n(c16) = n(c17) AND n(c17) = n(c18)) AS legs_same_length FROM $1"
}
lengths_a() {
	echo "SELECT 'A' AS source, count(*),
		sum(len(c11)), max(len(c11)), sum(len(c12)), max(len(c12)), sum(len(c13)), max(len(c13)),
		sum(len(c14)), max(len(c14)), sum(len(c15)), max(len(c15)),
		count(*) FILTER (len(c15) = len(c16) AND len(c16) = len(c17) AND len(c17) = len(c18)) FROM '$1/trade_A.parquet'"
}
lengths_b() {
	echo "SELECT 'B' AS source, count(*),
		sum(len(c11)), max(len(c11)), sum(len(c12)), max(len(c12)), sum(len(c13)), max(len(c13)),
		sum(len(c14)), max(len(c14)), sum(len(legs)), max(len(legs)), count(*) FROM '$1/trade_B.parquet'"
}
lengths_c() {
	echo "SELECT 'C' AS source, count(*),
		sum(len(c11)), max(len(c11)), sum(len(c12)), max(len(c12)), sum(len(c13)), max(len(c13)),
		sum(len(c14)), max(len(c14)), sum(len(legs)), max(len(legs)), count(*) FROM '$1/trade_C.parquet'"
}
flat_list() { # <dir> <table>: elements, longest list
	echo "(SELECT count(*) FROM '$1/pureflat/$2.parquet'),
		(SELECT max(n) FROM (SELECT count(*) AS n FROM '$1/pureflat/$2.parquet' GROUP BY ak0))"
}
lengths_flat() {
	echo "SELECT 'pure flat' AS source, (SELECT count(*) FROM '$1/pureflat/parent.parquet'),
		$(flat_list "$1" c11), $(flat_list "$1" c12), $(flat_list "$1" c13), $(flat_list "$1" c14),
		$(flat_list "$1" legs),
		(SELECT count(DISTINCT ak0) FROM '$1/pureflat/legs.parquet'
		 WHERE leg_id IS NOT NULL AND currency IS NOT NULL AND option_type IS NOT NULL AND value IS NOT NULL)"
}

flat_hash() { # <dir> <list>: B's list and the pure flat table, as sum(hash(sk, element))
	local fields=$2 elements="unnest($2) AS e"
	if [ "$2" = legs ]; then
		fields="leg_id, currency, option_type, value"
		elements="unnest(legs, recursive := true)"
	fi
	echo "SELECT '$2' AS list,
		(SELECT sum(hash(file_row_number, $([ "$2" = legs ] && echo "$fields" || echo e))::HUGEINT)
		 FROM (SELECT file_row_number, $elements FROM read_parquet('$1/trade_B.parquet', file_row_number = true))) AS b,
		(SELECT sum(hash(ak0, $fields)::HUGEINT) FROM '$1/pureflat/$2.parquet') AS pure_flat,
		(SELECT count(DISTINCT ak0) FROM '$1/pureflat/$2.parquet') AS parents_with_elements"
}

for version in distinct full; do
	DIR=$OUT/$version
	[ -f "$DIR/trade_B.parquet" ] || continue
	echo "## $version"
	echo
	SOURCE="read_csv('$CSV', header = false, delim = ',', quote = '\"', escape = '\"', columns = {$CSV_COLUMNS})"
	[ $version = distinct ] && SOURCE="(SELECT DISTINCT * FROM $SOURCE)"
	echo "### lengths"
	duck "
	CREATE MACRO n(s) AS CASE WHEN s = '[]' THEN 0 ELSE length(s) - length(replace(s, ',', '')) + 1 END;
	CREATE TABLE lengths AS
	$(lengths_csv "$SOURCE" csv) UNION ALL $(lengths_a "$DIR") UNION ALL $(lengths_b "$DIR") UNION ALL $(lengths_c "$DIR") UNION ALL $(lengths_flat "$DIR");
	FROM lengths;
	SELECT (SELECT count(*) FROM (SELECT DISTINCT * EXCLUDE (source) FROM lengths)) = 1 AS all_sources_agree;"
	echo
	echo "### content"
	duck "
	SELECT 'A = B, row by row' AS check, count(*) FILTER (a.row <> b.row) AS mismatches FROM
		(SELECT struct_pack($SCALARS, c11, c12, c13, c14, c15, c16, c17, c18) AS row FROM '$DIR/trade_A.parquet') a POSITIONAL JOIN
		(SELECT struct_pack($SCALARS, c11, c12, c13, c14,
		         c15 := [x.leg_id FOR x IN legs], c16 := [x.currency FOR x IN legs],
		         c17 := [x.option_type FOR x IN legs], c18 := [x.value FOR x IN legs]) AS row
		 FROM '$DIR/trade_B.parquet') b
	UNION ALL
	SELECT 'C = B, row by row (c11..c13 unwrapped)', count(*) FILTER (c.row <> b.row) FROM
		(SELECT struct_pack($SCALARS, c11 := [x.v FOR x IN c11], c12 := [x.v FOR x IN c12], c13 := [x.v FOR x IN c13],
		                    c14, legs) AS row FROM '$DIR/trade_C.parquet') c POSITIONAL JOIN
		(SELECT struct_pack($SCALARS, c11, c12, c13, c14, legs) AS row FROM '$DIR/trade_B.parquet') b
	UNION ALL
	SELECT 'parent = B scalars, sk = row number', count(*) FILTER (p.row <> b.row) FROM
		(SELECT struct_pack(sk, $SCALARS) AS row FROM '$DIR/pureflat/parent.parquet') p POSITIONAL JOIN
		(SELECT struct_pack(sk := file_row_number, $SCALARS) AS row FROM read_parquet('$DIR/trade_B.parquet', file_row_number = true)) b;"
	echo
	duck "$(flat_hash "$DIR" c11) UNION ALL $(flat_hash "$DIR" c12) UNION ALL $(flat_hash "$DIR" c13)
	      UNION ALL $(flat_hash "$DIR" c14) UNION ALL $(flat_hash "$DIR" legs)"
	echo "(b = pure_flat for every list, and parents_with_elements = the rows: no list is empty)"
	echo
done

if [ -f "$OUT/full/trade_A.parquet" ] && [ -f "$OUT/distinct/trade_A.parquet" ]; then
	echo "## full vs distinct: the same distinct rows"
	duck "
	CREATE VIEW f AS SELECT DISTINCT * FROM '$OUT/full/trade_A.parquet';
	SELECT (SELECT count(*) FROM f) AS distinct_rows_of_full, (SELECT count(*) FROM '$OUT/distinct/trade_A.parquet') AS rows_of_distinct,
	       (SELECT count(*) FROM (FROM f EXCEPT FROM '$OUT/distinct/trade_A.parquet')) AS only_in_full,
	       (SELECT count(*) FROM (FROM '$OUT/distinct/trade_A.parquet' EXCEPT FROM f)) AS only_in_distinct;"
	echo
fi

echo "## files"
echo '```'
for version in distinct full dims; do
	[ -d "$OUT/$version" ] && "$PY" -I "$HERE/page_counts.py" "$OUT/$version"
done
echo '```'
