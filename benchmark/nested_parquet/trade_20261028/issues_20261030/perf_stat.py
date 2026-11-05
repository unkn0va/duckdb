#!/usr/bin/env python3
"""perf stat counters and metrics of the second of two runs of a query (follow-ups G1, G2), in the five
configurations. The counters are switched on and off around that run through perf's control fifo, as in
profile_stacks.py. Leading SET / ATTACH lines of a query file are setup (time_queries.read_query).

EVENTS are perf events (comma separated), METRICS a metric group (-M, e.g. TopdownL1). Every counter and every
metric (the "metric-unit" of perf stat -j that names a tma_ metric, e.g. tma_bad_speculation) is one CSV row:
name, config, wall_s, item, value, unit. With MAXRSS=1 the run is wrapped in /usr/bin/time -v, and its
"Maximum resident set size" (of the whole process, both runs) is one more row (item max_rss, unit kB).
The raw perf stat output of every run is kept next to the CSV (<out>.raw/<name>.<config>.json).

Usage: [THREADS=1] [PERF=perf] [EVENTS=a,b] [METRICS=group] [MAXRSS=1] [CONFIGS="base ..."]
       perf_stat.py <query dir> <data dir> <out csv> <name> ...
Environment: BASE, PRENEST, FINAL as in time_queries.py
"""
import csv
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from time_queries import ALL_CONFIGS, read_query  # noqa: E402

THREADS = os.environ.get("THREADS", "1")
PERF = shlex.split(os.environ.get("PERF", "perf"))
EVENTS = os.environ.get("EVENTS", "")
METRICS = os.environ.get("METRICS", "")
MAXRSS = os.environ.get("MAXRSS") == "1"
CONFIGS = os.environ.get("CONFIGS", "base prenestoff prenest flat").split()


def measure(binary, setup, query, data_dir, raw_path, work_dir):
    """(wall seconds, [(item, value, unit)]) of the second run of the query."""
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        ctl, ack, toggle, out = (os.path.join(tmp, n) for n in ("ctl", "ack", "toggle.sh", "stat.json"))
        os.mkfifo(ctl)
        os.mkfifo(ack)
        with open(toggle, "w") as f:
            f.write(f'#!/bin/sh\necho "$1" > {ctl} && head -c 4 {ack} > /dev/null\n')
        os.chmod(toggle, 0o755)
        script = (f"SET threads = {THREADS};\n{setup}\n.mode trash\n{query};\n.timer on\n"
                  f".shell {toggle} enable\n{query};\n.shell {toggle} disable\n")
        selection = (["-e", EVENTS] if EVENTS else []) + (["-M", METRICS] if METRICS else [])
        command = [*PERF, "stat", "-j", *selection, "-D", "-1", "--control", f"fifo:{ctl},{ack}", "-o", out,
                   "--", binary, "-no-agent"]
        if MAXRSS:
            command = ["/usr/bin/time", "-v", *command]
        run = subprocess.run(command, input=script, text=True, capture_output=True, cwd=data_dir)
        timings = re.findall(r"Run Time \(s\): real ([0-9.]+)", run.stdout + run.stderr)
        if run.returncode or not timings:
            raise RuntimeError((run.stderr or run.stdout).strip()[-400:])
        text = open(out).read()
    with open(raw_path, "w") as f:
        f.write(text)
    items = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        event = entry.get("event", "").split(":")[0]
        value = entry.get("counter-value", "")
        if event and not value.startswith("<"):
            items.append((event, value, entry.get("unit", "")))
        unit = entry.get("metric-unit", "")
        match = re.search(r"(tma_\w+)", unit)
        if match and entry.get("metric-value") not in (None, ""):
            items.append((match.group(1), entry["metric-value"], unit.replace(match.group(1), "").strip() or "%"))
        if event and value.startswith("<"):
            items.append((event, value, "not counted"))
    rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)", run.stderr)
    if rss:
        items.append(("max_rss", rss.group(1), "kB"))
    return float(timings[-1]), items


def main():
    query_dir, data_dir, out_csv, *names = sys.argv[1:]
    data_dir = os.path.abspath(data_dir)
    raw_dir = out_csv + ".raw"
    os.makedirs(raw_dir, exist_ok=True)
    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "config", "wall_s", "item", "value", "unit"])
        for name in names:
            for config in CONFIGS:
                binary, config_setup, variant = ALL_CONFIGS[config]
                path = os.path.join(query_dir, f"{name}.{variant}.sql")
                if not os.path.exists(path):
                    continue
                file_setup, query = read_query(path)
                try:
                    wall, items = measure(binary, config_setup + "\n" + file_setup, query, data_dir,
                                          os.path.join(raw_dir, f"{name}.{config}.json"),
                                          os.path.dirname(os.path.abspath(out_csv)))
                except RuntimeError as e:
                    writer.writerow([name, config, "", "error", str(e).splitlines()[-1][:200], ""])
                    print(f"{name:22} {config:10} ERROR {str(e).splitlines()[-1][:150]}", flush=True)
                    continue
                for item, value, unit in items:
                    writer.writerow([name, config, f"{wall:.3f}", item, value, unit])
                f.flush()
                shown = ", ".join(f"{i} {v}" for i, v, _ in items if i in ("branch-misses", "cycles", "page-faults",
                                                                             "tma_bad_speculation", "max_rss"))
                print(f"{name:22} {config:10} {wall:8.3f} s  {shown}", flush=True)


if __name__ == "__main__":
    main()
