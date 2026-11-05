#!/usr/bin/env python3
"""The synthetic files of follow-up G4: <data>/../syn/syn_L<L>.parquet, LISTS rows with one column c LIST<BIGINT> of
exactly L elements, c[j] of row i = hash(i * L + j) % 1000000 (so v < 500000 passes about half), for L = 1, 2, 4, 8,
16, 32. DuckDB writes the values to a temporary file, write_trade.py --restream rewrites it with trade_B's writer
settings (pyarrow 26.0.0, snappy) and row groups (122,880 rows), and the two are compared (rows, elements,
sum(hash(file_row_number, c))) before the temporary file is removed. Prints a markdown table.

Usage: [LISTS=100000000] [THREADS=20] make_syn.py <data dir>
Environment: BASE (binary), PY (python with pyarrow 26.0.0)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NB = os.path.expanduser("~/nested-bench")
BASE = os.environ.get("BASE", f"{NB}/duckdb_base/build/release/duckdb")
PY = os.environ.get("PY", f"{NB}/venv/bin/python")
LISTS = int(os.environ.get("LISTS", "100000000"))
THREADS = os.environ.get("THREADS", "20")
L_VALUES = (1, 2, 4, 8, 16, 32)


def duckdb(cwd, sql):
    run = subprocess.run([BASE, "-no-agent", "-csv", "-noheader", "-c", f"SET threads = {THREADS};", "-c", sql],
                         capture_output=True, text=True, cwd=cwd)
    if run.returncode or run.stderr.strip():
        sys.exit(f"duckdb failed: {run.stderr.strip()[-300:]}")
    return run.stdout.strip()


def check(cwd, path):
    return duckdb(cwd, f"SELECT count(*), sum(len(c)), sum(hash(file_row_number, c))::HUGEINT "
                       f"FROM read_parquet('{path}', file_row_number = true)")


def main():
    root = os.path.dirname(os.path.abspath(sys.argv[1]))
    folder = os.path.join(root, "syn")
    os.makedirs(folder, exist_ok=True)
    print("| file | rows | elements | content (rows, elements, hash) = DuckDB's | size GB |\n|---|---|---|---|---|")
    for n in L_VALUES:
        target = os.path.join(folder, f"syn_L{n}.parquet")
        temp = os.path.join(folder, f".syn_L{n}.duckdb.parquet")
        if not os.path.exists(target):
            duckdb(folder, f"COPY (SELECT list_transform(range({n}), lambda j: (hash(i * {n} + j) % 1000000)::BIGINT) AS c "
                           f"FROM range({LISTS}) t(i) ORDER BY i) TO '{os.path.basename(temp)}' (FORMAT parquet);")
            subprocess.run([PY, "-I", os.path.join(HERE, "..", "write_trade.py"), "--restream", temp, target],
                           check=True, capture_output=True)
            same = check(folder, os.path.basename(temp)) == check(folder, os.path.basename(target))
            os.remove(temp)
        else:
            same = None
        rows, elements, _ = check(folder, os.path.basename(target)).split(",")
        verdict = {True: "yes", False: "NO", None: "(already there)"}[same]
        print(f"| syn_L{n}.parquet | {int(rows):,} | {int(elements):,} | {verdict} | "
              f"{os.path.getsize(target) / 1e9:.2f} |", flush=True)


if __name__ == "__main__":
    main()
