#!/usr/bin/env python3
"""Where the time of a query goes, by operator kind, from EXPLAIN (ANALYZE, FORMAT json): one run per query and
configuration, by default with 1 thread (the operator timings are then wall-clock time of that thread).

Kinds: scan (TABLE_SCAN - the Parquet scan, including the assembly of the lists it returns, and read_parquet_flat's
node scans), unnest, hash_join, other_join, aggregate, filter, other (projections, order by, ...). Also the query's
total_time and cpu_time from the profile, and the operator types seen.

Usage: [THREADS=1] operator_times.py <query dir> <data dir> <out csv> [<query> ...]
Environment: BASE, PRENEST, FINAL as in check_queries.py
"""
import csv
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_queries import CONFIGS  # noqa: E402

THREADS = os.environ.get("THREADS", "1")
KINDS = ["scan", "unnest", "hash_join", "other_join", "aggregate", "filter", "other"]
SKIP = {"RESULT_COLLECTOR", "EXPLAIN_ANALYZE"}


def kind(operator):
    if operator.endswith("SCAN"):
        return "scan"
    if operator == "UNNEST":
        return "unnest"
    if operator == "HASH_JOIN":
        return "hash_join"
    if "JOIN" in operator or operator == "CROSS_PRODUCT":
        return "other_join"
    if "GROUP_BY" in operator or "AGGREGATE" in operator:
        return "aggregate"
    if operator == "FILTER":
        return "filter"
    return "other"


def profile(binary, setup, sql, cwd):
    query = f"SET threads = {THREADS}; {setup} EXPLAIN (ANALYZE, FORMAT json) {sql.strip().rstrip(';')}"
    run = subprocess.run(
        [binary, "-no-agent", "-list", "-noheader", "-c", query], capture_output=True, text=True, cwd=cwd
    )
    if run.returncode:
        raise RuntimeError(run.stderr.strip()[:300])
    out = run.stdout
    return json.loads(out[out.index("{") : out.rindex("}") + 1])


def main():
    query_dir, data_dir, out_csv, *only = sys.argv[1:]
    names = sorted({f.split(".")[0] for f in os.listdir(query_dir) if f.endswith(".sql")})
    names = [n for n in names if not only or n in only]
    seen = set()
    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["query", "config", "threads", "total_s", "cpu_s"] + [f"{k}_s" for k in KINDS] + ["operators"])
        for name in names:
            for label, binary, setup, variant in CONFIGS:
                sql = open(os.path.join(query_dir, f"{name}.{variant}.sql")).read()
                result = profile(binary, setup, sql, data_dir)
                times, operators = dict.fromkeys(KINDS, 0.0), []

                def walk(node):
                    if node["type"] not in SKIP:
                        times[kind(node["type"])] += node["timing"]
                        operators.append(node["type"])
                    for child in node.get("children", []):
                        walk(child)

                for node in result["operator"]:
                    walk(node)
                seen.update(operators)
                writer.writerow(
                    [name, label, THREADS, f"{result['query']['total_time']:.4f}", f"{result['query']['cpu_time']:.4f}"]
                    + [f"{times[k]:.4f}" for k in KINDS]
                    + [" ".join(operators)]
                )
                f.flush()
    print("operator types:", ", ".join(sorted(seen)))


if __name__ == "__main__":
    main()
