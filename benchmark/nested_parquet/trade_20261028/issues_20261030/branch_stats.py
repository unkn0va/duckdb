#!/usr/bin/env python3
"""Branch misses of the element conditions (issue 1-2: is the per-element cost of q2_c highest near 50% because of
mispredicted branches?). perf stat counts branches, branch-misses, instructions and cycles of the second of two runs
of a query in one CLI process (the counters are switched on and off around it, as in profile_stacks.py).

Writes <out csv> (query, config, wall_s, branches, branch_misses, miss_pct, instructions, cycles) and prints a
markdown table: branch-miss % per query and configuration.

Usage: [THREADS=1] [PERF=perf] [EVENTS=branches,branch-misses,instructions,cycles] [CONFIGS="base prenestoff prenest flat"] [QUERIES="q2_c01 ..."]
       branch_stats.py <data dir> <out csv>
Environment: BASE, PRENEST, FINAL as in time_queries.py
"""
import csv
import os
import re
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from time_queries import ALL_CONFIGS, read_query  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
QUERY_DIR = os.path.join(HERE, "..", "queries")
THREADS = os.environ.get("THREADS", "1")
PERF = shlex.split(os.environ.get("PERF", "perf"))
CONFIGS = os.environ.get("CONFIGS", "base prenestoff prenest flat").split()
QUERIES = os.environ.get(
    "QUERIES", "q2_c01 q2_c10 q2_c25 q2_c50 q2_c75 q2_s01 q2_s10 q2_s50 q2_s90"
).split()
EVENTS = os.environ.get("EVENTS", "branches,branch-misses,instructions,cycles").split(",")


def measure(binary, setup, query, data_dir):
    """(wall seconds, {event: count or None}) of the second run of the query."""
    with tempfile.TemporaryDirectory(dir=os.path.abspath(os.path.dirname(OUT_CSV) or ".")) as tmp:
        ctl, ack, toggle, out = (os.path.join(tmp, n) for n in ("ctl", "ack", "toggle.sh", "stat.csv"))
        os.mkfifo(ctl)
        os.mkfifo(ack)
        with open(toggle, "w") as f:
            f.write(f'#!/bin/sh\necho "$1" > {ctl} && head -c 4 {ack} > /dev/null\n')
        os.chmod(toggle, 0o755)
        script = (
            f"SET threads = {THREADS};\n{setup}\n.mode trash\n{query};\n.timer on\n"
            f".shell {toggle} enable\n{query};\n.shell {toggle} disable\n"
        )
        run = subprocess.run(
            [*PERF, "stat", "-x", ",", "-e", ",".join(EVENTS), "-D", "-1", "--control", f"fifo:{ctl},{ack}",
             "-o", out, "--", binary, "-no-agent"],
            input=script, text=True, capture_output=True, cwd=data_dir,
        )
        timings = re.findall(r"Run Time \(s\): real ([0-9.]+)", run.stdout + run.stderr)
        if run.returncode or not timings:
            raise RuntimeError((run.stderr or run.stdout).strip()[-300:])
        counts = {}
        for line in open(out):
            fields = line.strip().split(",")
            # "branches", or "branches:u" when only user space may be counted
            if len(fields) > 2 and fields[2].split(":")[0] in EVENTS:
                try:
                    counts[fields[2].split(":")[0]] = round(float(fields[0]))
                except ValueError:  # <not supported>, <not counted>
                    counts[fields[2].split(":")[0]] = None
        return float(timings[-1]), counts


OUT_CSV = ""


def main():
    global OUT_CSV
    data_dir, OUT_CSV = os.path.abspath(sys.argv[1]), sys.argv[2]
    rows = []
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["query", "config", "wall_s", "branches", "branch_misses", "miss_pct", "instructions", "cycles",
                         "error"])
        for query in QUERIES:
            for config in CONFIGS:
                binary, config_setup, variant = ALL_CONFIGS[config]
                file_setup, sql = read_query(os.path.join(QUERY_DIR, f"{query}.{variant}.sql"))
                try:
                    wall, c = measure(binary, config_setup + "\n" + file_setup, sql, data_dir)
                    b, m = c.get("branches"), c.get("branch-misses")
                    pct = f"{100 * m / b:.3f}" if b and m is not None else ""
                    row = [query, config, f"{wall:.3f}", b, m, pct, c.get("instructions"), c.get("cycles"), ""]
                except RuntimeError as e:
                    row = [query, config, "", "", "", "", "", "", str(e).splitlines()[-1][:200]]
                writer.writerow(row)
                f.flush()
                rows.append(row)
                print(f"{query:8} {config:10} {row[2]:>8} s  branch-miss {row[5] or row[8] or 'not counted'}%",
                      flush=True)
    table = {(r[0], r[1]): r for r in rows}
    print("\n| 쿼리 | " + " | ".join(f"{c} miss % (misses, 백만)" for c in CONFIGS) + " |")
    print("|---|" + "---|" * len(CONFIGS))
    for query in QUERIES:
        cells = []
        for config in CONFIGS:
            r = table.get((query, config))
            cells.append(f"{r[5]} ({r[4] / 1e6:.0f})" if r and r[5] else "·")
        print(f"| {query} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
