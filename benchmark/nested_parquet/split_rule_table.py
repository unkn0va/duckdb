#!/usr/bin/env python3
"""Table of the split-rule experiment (SERVER.md, step 9): read_parquet_flat with parquet_node_split_half_threads on
and off, measured interleaved by run_bench.py with the labels on/off (or on_<layout>/off_<layout> for the runs pinned
to a CPU layout). For every query and thread count it shows the wall (CPU) seconds of both settings, off/on, and how
many row groups the scans split with each setting - read from the debug log of one more run per setting, so that the
comparisons where the plans differ are marked. Where the plans are the same, off/on is the noise of the measurement.
<dataset>_pinned.csv holds the runs pinned to CPU layouts (cpu_layouts.py), with 10 threads.
Usage: split_rule_table.py <result folder> <duckdb> <data folder>
"""
import csv
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIRS = {"tpch_sf10": "nested-parquet-datasets/nested-tpch-sf10", "dblp": "nested-parquet-datasets/dblp"}
PINNED_THREADS = 10


def split_row_groups(duckdb, data_dir, sql, threads, half):
    """The number of row groups that the scans of the query split, and of those that count levels"""
    log = ("SELECT count(*) FILTER (message LIKE 'read_parquet_node: row group % is scanned in % parts%'), "
           "count(*) FILTER (message LIKE 'read_parquet_node: row group % parts%counting levels%') FROM duckdb_logs")
    setup = (f"SET threads = {threads}; SET parquet_node_split_half_threads = {half}; "
             "CALL enable_logging(level := 'debug', storage := 'memory')")
    proc = subprocess.run([duckdb, "-no-agent", "-csv", "-noheader", "-c", setup, "-c", sql.strip().rstrip(";") + ";",
                           "-c", log], cwd=data_dir, capture_output=True, text=True, timeout=1800)
    last = proc.stdout.strip().splitlines()[-1] if proc.returncode == 0 and proc.stdout.strip() else ""
    if not re.fullmatch(r"\d+,\d+", last):
        return "?"
    split, counted = last.split(",")
    return f"{split} ({counted})"


def main():
    folder, duckdb, data = sys.argv[1], os.path.abspath(sys.argv[2]), sys.argv[3]
    noise = []
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        name = os.path.basename(path)[:-4]
        dataset = re.sub(r"_pinned$", "", name)
        if dataset not in DATA_DIRS:
            continue
        rows = list(csv.DictReader(line for line in open(path) if not line.startswith("#")))
        configs = sorted({(m.group(1), int(m.group(2) or PINNED_THREADS)) for key in rows[0]
                          for m in [re.fullmatch(r"flat_on((?:_one|_two|_ht)?)(?:_t(\d+))?_s", key)] if m})
        print(f"## {name}\n")
        print("Seconds of the fastest run (CPU seconds); split row groups: all (of them with a level count), "
              "`<<` marks the comparisons where the plans differ.\n")
        print("| query | threads | layout | on | off | off/on | split on | split off |")
        print("|---|---|---|---|---|---|---|---|")
        plans = {}
        for row in rows:
            query = row["query"]
            sql = open(os.path.join(HERE, "queries", dataset, f"{query}.flat.sql")).read()
            for layout, threads in configs:
                suffix = "" if layout else f"_t{threads}"
                on, off = f"flat_on{layout}{suffix}", f"flat_off{layout}{suffix}"
                if not row.get(on + "_s") or not row.get(off + "_s"):
                    continue
                for half in ("true", "false"):
                    if (query, threads, half) not in plans:
                        plans[query, threads, half] = split_row_groups(duckdb, os.path.join(data, DATA_DIRS[dataset]),
                                                                       sql, threads, half)
                split_on, split_off = plans[query, threads, "true"], plans[query, threads, "false"]
                ratio = float(row[off + "_s"]) / float(row[on + "_s"])
                same_result = row.get(on + "_result") == row.get(off + "_result")
                differs = split_on != split_off
                if not differs:
                    noise.append(abs(ratio - 1))
                print(f"| {query} | {threads} | {layout.lstrip('_') or 'free'} "
                      f"| {float(row[on + '_s']):.3f} ({float(row[on + '_cpu']):.2f}) "
                      f"| {float(row[off + '_s']):.3f} ({float(row[off + '_cpu']):.2f}) "
                      f"| {ratio:.2f}{' <<' if differs else ''}{'' if same_result else ' RESULT DIFFERS'} "
                      f"| {split_on} | {split_off} |")
        print()
    if noise:
        print(f"Noise (same plans): off/on differs from 1 by at most {max(noise):.2f}, "
              f"by {sorted(noise)[len(noise) // 2]:.2f} in the median.")


if __name__ == "__main__":
    main()
