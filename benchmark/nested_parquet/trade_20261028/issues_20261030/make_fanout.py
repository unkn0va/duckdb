#!/usr/bin/env python3
"""The data of follow-up D (queries_fanout/): dimension tables with k dates per scenario, as parquet and as DuckDB
tables, and the fact tables as DuckDB tables.

  <data>/../dims_k/dim_k<k>.parquet   reg_scenario (every value of c8) x k dates from 2021-09-01, columns and types
                                      of dims/date_plots_flat.parquet; k = 1, 2, 4, 8, 16
  <data>/../fanout/fanout.duckdb      dim_k<k> (the same rows); unless FACT=0 also trade_b (c8, legs of trade_B),
                                      parent (sk, c8) and legs (ak0, value) of pureflat/ - only the columns the
                                      queries read, in file order

Usage: [FACT=0] [THREADS=20] make_fanout.py <data dir>
Environment: BASE (binary, default ~/nested-bench/duckdb_base/build/release/duckdb)
"""
import os
import subprocess
import sys

BASE = os.environ.get("BASE", os.path.expanduser("~/nested-bench/duckdb_base/build/release/duckdb"))
THREADS = os.environ.get("THREADS", "20")
K = (1, 2, 4, 8, 16)


def duckdb(data_dir, sql, database=":memory:"):
    run = subprocess.run([BASE, "-no-agent", "-csv", "-noheader", database], input=f"SET threads = {THREADS};\n{sql}",
                         text=True, capture_output=True, cwd=data_dir)
    if run.returncode or run.stderr.strip():
        sys.exit(f"duckdb failed: {run.stderr.strip()[-300:]}")
    return run.stdout


def main():
    data_dir = os.path.abspath(sys.argv[1])
    root = os.path.dirname(data_dir)
    os.makedirs(os.path.join(root, "dims_k"), exist_ok=True)
    os.makedirs(os.path.join(root, "fanout"), exist_ok=True)
    for k in K:
        duckdb(data_dir, f"""COPY (SELECT s.c8 AS reg_scenario, (DATE '2021-09-01' + i::INTEGER) AS plot_date
              FROM (SELECT DISTINCT c8 FROM 'pureflat/parent.parquet') s, range({k}) t(i) ORDER BY 1, 2)
              TO '../dims_k/dim_k{k}.parquet' (FORMAT parquet);""")
    database = os.path.join(root, "fanout", "fanout.duckdb")
    for path in (database, database + ".wal"):
        if os.path.exists(path):
            os.remove(path)
    tables = [f"CREATE TABLE dim_k{k} AS SELECT * FROM '../dims_k/dim_k{k}.parquet';" for k in K]
    if os.environ.get("FACT", "1") != "0":
        tables += [
            "CREATE TABLE trade_b AS SELECT c8, legs FROM 'trade_B.parquet';",
            "CREATE TABLE parent AS SELECT sk, c8 FROM 'pureflat/parent.parquet';",
            "CREATE TABLE legs AS SELECT ak0, value FROM 'pureflat/legs.parquet';",
        ]
    duckdb(data_dir, "\n".join(tables) + "\nCHECKPOINT;", database)
    counts = duckdb(data_dir, "SELECT table_name, estimated_size FROM duckdb_tables() ORDER BY 1;", database)
    print("| table | rows |\n|---|---|")
    for line in counts.split():
        name, rows = line.split(",")
        print(f"| {name} | {int(rows):,} |")
    print(f"\n{database}: {os.path.getsize(database) / 1e9:.2f} GB")


if __name__ == "__main__":
    main()
