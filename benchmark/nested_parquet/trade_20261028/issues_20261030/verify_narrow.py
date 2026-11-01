#!/usr/bin/env python3
"""Check a narrowed copy of trade_B (write_trade.py --narrow) against trade_B, as verify_trade.sh checks the files of
prepare_trade.sh: the same rows, elements and longest list; the same content - sum(hash(file_row_number, every other
column)) and sum(hash(file_row_number, the kept fields of every element)); the same row groups (rows of each) and
writer (created_by, compression). Prints a markdown table; the last column says whether B and the copy agree.

Usage: verify_narrow.py <data dir> <trade_Bn.parquet> <field,field>
Environment: BASE (binary, default ~/nested-bench/duckdb_base/build/release/duckdb)
"""
import os
import subprocess
import sys

BASE = os.environ.get("BASE", os.path.expanduser("~/nested-bench/duckdb_base/build/release/duckdb"))
SCALARS = [f"c{i}" for i in list(range(0, 15)) + list(range(19, 23))]


def query(data_dir, sql):
    run = subprocess.run([BASE, "-no-agent", "-csv", "-noheader", "-c", "SET threads = 20;", "-c", sql],
                         capture_output=True, text=True, cwd=data_dir, check=True)
    return run.stdout.strip()


def main():
    data_dir, narrow, fields = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3].split(",")
    kept = "struct_pack(" + ", ".join(f"{f} := x.{f}" for f in fields) + ")"
    checks = {
        "rows, elements, longest list": "SELECT count(*), sum(len(legs)), max(len(legs)) FROM read_parquet('{f}')",
        "hash of the other columns": f"SELECT sum(hash(file_row_number, {', '.join(SCALARS)})::HUGEINT) "
        "FROM read_parquet('{f}', file_row_number = true)",
        f"hash of the elements ({', '.join(fields)})": f"SELECT sum(hash(file_row_number, "
        f"list_transform(legs, lambda x: {kept}))::HUGEINT) FROM read_parquet('{{f}}', file_row_number = true)",
        "row groups (count, rows of each)": "SELECT count(*), string_agg(row_group_num_rows::VARCHAR, ' ' ORDER BY "
        "row_group_id) FROM (SELECT DISTINCT row_group_id, row_group_num_rows FROM parquet_metadata('{f}'))",
        "writer, compression": "SELECT (SELECT created_by FROM parquet_file_metadata('{f}')), "
        "string_agg(DISTINCT compression, ' ') FROM parquet_metadata('{f}')",
    }
    print(f"| check | trade_B.parquet | {os.path.basename(narrow)} | same |\n|---|---|---|---|")
    for name, sql in checks.items():
        a, b = query(data_dir, sql.format(f="trade_B.parquet")), query(data_dir, sql.format(f=narrow))
        short = lambda v: v if len(v) < 60 else v[:28] + " … " + v[-24:]  # noqa: E731
        print(f"| {name} | {short(a)} | {short(b)} | {'yes' if a == b else 'NO'} |")


if __name__ == "__main__":
    main()
