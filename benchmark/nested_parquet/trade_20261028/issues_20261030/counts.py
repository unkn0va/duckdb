#!/usr/bin/env python3
"""The number of lists and elements a trade query works on (issue 1-2), from base's EXPLAIN ANALYZE of its builtin
query and from the file:
  lists_total      rows of the file (every row has one list of the unnested column, none is NULL or empty in trade)
  elements_total   elements of that list column (sum of len)
  lists_scanned    rows the scan returns (after a top-level filter such as q1's c9 < x)
  elements_unnested  rows out of UNNEST
  elements_passing   rows out of the FILTER above UNNEST (= elements_unnested without one)

Usage: [THREADS=20] counts.py <data dir> <out csv> <builtin query file> ...
Environment: BASE (binary, default ~/nested-bench/duckdb_base/build/release/duckdb)
"""
import csv
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plans import explain_analyze, operators  # noqa: E402

BASE = os.environ.get("BASE", os.path.expanduser("~/nested-bench/duckdb_base/build/release/duckdb"))
THREADS = os.environ.get("THREADS", "20")


def main():
    data_dir, out_csv, *files = sys.argv[1:]
    totals = {}
    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["query", "column", "lists_total", "elements_total", "lists_scanned", "elements_unnested",
                         "elements_passing"])
        for path in files:
            query = open(path).read()
            column, table = re.search(r"unnest\((\w+)\).*?FROM ('[^']+')", query, re.S).groups()
            if (column, table) not in totals:
                out = subprocess.run(
                    [BASE, "-no-agent", "-csv", "-noheader", "-c",
                     f"SET threads = {THREADS}; SELECT count(*), sum(len({column})) FROM {table}"],
                    capture_output=True, text=True, cwd=data_dir, check=True,
                ).stdout.strip()
                totals[(column, table)] = out.split(",")
            ops = operators(explain_analyze(BASE, data_dir, "", query, THREADS))
            unnest = next(op for op in ops if op["type"] == "UNNEST")
            scan = next(op for op in ops if op["type"] == "TABLE_SCAN" and op["parent"] == unnest["id"])
            passing, cur = unnest["actual"], unnest
            while cur["parent"] is not None:
                cur = ops[cur["parent"]]
                if cur["type"] == "FILTER":
                    passing = cur["actual"]
                    break
                if cur["type"] != "PROJECTION":
                    break
            name = os.path.basename(path).split(".")[0]
            writer.writerow([name, column, *totals[(column, table)], scan["actual"], unnest["actual"], passing])
            print(name, column, *totals[(column, table)], scan["actual"], unnest["actual"], passing, flush=True)


if __name__ == "__main__":
    main()
