#!/usr/bin/env python3
"""Benchmark nested Parquet queries in the variants of a query directory with the DuckDB CLI.

A query directory holds <name>.<variant>.sql files, variants: builtin (DuckDB nested types), node (read_parquet_node
with manual joins), split (the paper's pre-split files) and flat (read_parquet_flat). Each query runs RUNS times in one
CLI process (the first run warms the OS cache) and the fastest run is reported, as in the paper. The results of the
variants are compared by an order-insensitive hash. THREADS sets the number of threads (default: all cores).

Usage: run_bench.py <duckdb binary> <query dir> <data dir> <result csv>
"""
import csv
import os
import re
import subprocess
import sys

DUCKDB = sys.argv[1]
QUERY_DIR = sys.argv[2]
DATA_DIR = sys.argv[3]
OUT_CSV = sys.argv[4]
RUNS = int(os.environ.get("RUNS", "5"))
THREADS = os.environ.get("THREADS")
TIMEOUT = int(os.environ.get("QUERY_TIMEOUT", "600"))


def run_timed(sql):
    setup = f"SET threads = {THREADS};\n" if THREADS else ""
    script = setup + ".timer on\n.mode trash\n" + "\n".join([sql.strip().rstrip(";") + ";"] * RUNS) + "\n"
    try:
        proc = subprocess.run([DUCKDB, "-no-agent"], input=script, capture_output=True, text=True, cwd=DATA_DIR,
                              timeout=TIMEOUT * RUNS)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    times = [float(t) for t in re.findall(r"Run Time \(s\): real ([0-9.]+)", proc.stdout + proc.stderr)]
    if proc.returncode != 0 or len(times) != RUNS:
        return None, (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["error"]
    return min(times), ""


def result_hash(sql):
    # order-insensitive fingerprint of the result, with numbers rounded to absorb float summation order
    inner = sql.strip().rstrip(";")
    query = ("SELECT count(*), hash(list(r ORDER BY r)) FROM (SELECT list_transform(list_value(COLUMNS(*)::VARCHAR), "
             "lambda x: CASE WHEN TRY_CAST(x AS DOUBLE) IS NULL THEN x ELSE round(x::DOUBLE, 2)::VARCHAR END)::VARCHAR AS r "
             f"FROM ({inner}))")
    proc = subprocess.run([DUCKDB, "-no-agent", "-csv", "-noheader", "-c", query], capture_output=True, text=True,
                          cwd=DATA_DIR, timeout=TIMEOUT)
    return proc.stdout.strip() if proc.returncode == 0 else "error: " + proc.stderr.strip()[-200:]


VARIANTS = ("builtin", "node", "split", "flat")
rows = []
names = sorted({f.rsplit(".", 2)[0] for f in os.listdir(QUERY_DIR) if f.endswith(".sql")})
for name in names:
    entry = {"query": name}
    for variant in VARIANTS:
        path = os.path.join(QUERY_DIR, f"{name}.{variant}.sql")
        if not os.path.exists(path):
            continue
        sql = open(path).read()
        seconds, error = run_timed(sql)
        entry[f"{variant}_s"] = "" if seconds is None else f"{seconds:.4f}"
        entry[f"{variant}_error"] = error if isinstance(error, str) else " ".join(error)
        entry[f"{variant}_result"] = result_hash(sql) if seconds is not None else "n/a"
    if entry.get("builtin_s") and entry.get("node_s"):
        entry["builtin_over_node"] = f"{float(entry['builtin_s']) / float(entry['node_s']):.2f}"
    if entry.get("split_s") and entry.get("node_s"):
        entry["node_over_split"] = f"{float(entry['node_s']) / float(entry['split_s']):.2f}"
    if entry.get("flat_s") and entry.get("node_s"):
        entry["flat_over_node"] = f"{float(entry['flat_s']) / float(entry['node_s']):.2f}"
    entry["flat_matches_builtin"] = str(entry.get("builtin_result") == entry.get("flat_result"))
    entry["node_matches_builtin"] = str(entry.get("builtin_result") == entry.get("node_result"))
    rows.append(entry)
    print(entry, flush=True)

fields = ["query", "builtin_s", "node_s", "split_s", "builtin_over_node", "node_over_split", "flat_s", "flat_over_node", "flat_matches_builtin", "node_matches_builtin",
          "builtin_error", "node_error", "split_error", "builtin_result", "node_result", "split_result", "flat_result", "flat_error"]
with open(OUT_CSV, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
