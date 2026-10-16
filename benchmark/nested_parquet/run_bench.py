#!/usr/bin/env python3
"""Benchmark nested Parquet queries in the variants of a query directory with the DuckDB CLI.

A query directory holds <name>.<variant>.sql files, variants: builtin (DuckDB nested types), node (read_parquet_node
with manual joins), split (the paper's pre-split files), flat (read_parquet_flat), flat_umbra / flat_minmax (XMark
queries over read_parquet_flat: Umbra's correlated subqueries / a join with the min/max key per parent). Each query runs
RUNS times in one CLI process (the first run warms the OS cache); the fastest wall-clock time (_s) and the smallest
CPU time of all threads (user + sys, _cpu) are reported. The results of the variants are compared by an
order-insensitive hash with the builtin query - or with <name>.<variant>.oracle, a query whose result the variant has
by definition when it differs from the builtin one.

Several binaries (label=path,label=path) and thread counts (THREADS=1,16) can be compared: they run interleaved, one
after the other for every variant, so that they see the same state of the machine (the timings of a laptop drift by
tens of percent within an hour). Their columns get the suffix _<label>_t<threads> (parts that do not vary are left out).

Before every query the CPU use of the other processes is sampled; when they keep a core busy a warning is printed and
the CPU use is recorded in the busy_cpu column, as their load distorts the timings.

Usage: [RUNS=n] [THREADS=n[,n...]] run_bench.py <duckdb binary | label=path,...> <query dir> <data dir> <result csv>
"""
import csv
import os
import re
import subprocess
import sys
import time

QUERY_DIR = sys.argv[2]
DATA_DIR = sys.argv[3]
OUT_CSV = sys.argv[4]
RUNS = int(os.environ.get("RUNS", "5"))
TIMEOUT = int(os.environ.get("QUERY_TIMEOUT", "600"))

BINARIES = []
for entry in sys.argv[1].split(","):
    label, _, path = entry.rpartition("=")
    BINARIES.append((label or "duckdb", path))
THREADS = [t for t in os.environ.get("THREADS", "").split(",") if t] or [None]
CONFIGS = []
for label, path in BINARIES:
    for threads in THREADS:
        parts = ([label] if len(BINARIES) > 1 else []) + ([f"t{threads}"] if len(THREADS) > 1 else [])
        CONFIGS.append({"label": label, "path": path, "threads": threads,
                        "suffix": "".join("_" + part for part in parts)})
DUCKDB = BINARIES[0][1]


def run_timed(sql, binary, threads):
    setup = f"SET threads = {threads};\n" if threads else ""
    script = setup + ".timer on\n.mode trash\n" + "\n".join([sql.strip().rstrip(";") + ";"] * RUNS) + "\n"
    try:
        proc = subprocess.run([binary, "-no-agent"], input=script, capture_output=True, text=True, cwd=DATA_DIR,
                              timeout=TIMEOUT * RUNS)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    timings = re.findall(r"Run Time \(s\): real ([0-9.]+) user ([0-9.]+) sys ([0-9.]+)", proc.stdout + proc.stderr)
    if proc.returncode != 0 or len(timings) != RUNS:
        return None, (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["error"]
    wall = min(float(real) for real, _, _ in timings)
    cpu = min(float(user) + float(sys) for _, user, sys in timings)
    return (wall, cpu), ""


def result_hash(sql, binary=None):
    # order-insensitive fingerprint of the result, with numbers rounded to absorb float summation order
    inner = sql.strip().rstrip(";")
    query = ("SELECT count(*), hash(list(r ORDER BY r)) FROM (SELECT list_transform(list_value(COLUMNS(*)::VARCHAR), "
             "lambda x: CASE WHEN TRY_CAST(x AS DOUBLE) IS NULL THEN x ELSE round(x::DOUBLE, 2)::VARCHAR END)::VARCHAR AS r "
             f"FROM ({inner}))")
    proc = subprocess.run([binary or DUCKDB, "-no-agent", "-csv", "-noheader", "-c", query], capture_output=True, text=True,
                          cwd=DATA_DIR, timeout=TIMEOUT)
    return proc.stdout.strip() if proc.returncode == 0 else "error: " + proc.stderr.strip()[-200:]


VARIANTS = ("builtin", "node", "split", "flat", "flat_umbra", "flat_minmax")
#: Other processes using more than this (in % of one core, summed) make the timings unreliable
BUSY_CPU_THRESHOLD = 50.0


def process_cpu_ticks():
    result = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/stat") as f:
                fields = f.read().rsplit(")", 1)[1].split()
            # utime and stime: fields 14 and 15 of /proc/<pid>/stat, counted after the command name
            result[int(pid)] = int(fields[11]) + int(fields[12])
        except (OSError, ValueError, IndexError):
            continue
    return result


def busy_processes(interval=0.5):
    """The processes other than this one that use CPU, as (% of one core, pid, command line)."""
    if not os.path.isdir("/proc"):
        return []
    before = process_cpu_ticks()
    time.sleep(interval)
    after = process_cpu_ticks()
    ticks_per_second = os.sysconf("SC_CLK_TCK")
    result = []
    for pid, ticks in after.items():
        if pid == os.getpid() or pid not in before:
            continue
        percent = 100.0 * (ticks - before[pid]) / ticks_per_second / interval
        if percent >= 5.0:
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    command = f.read().replace(b"\0", b" ").decode(errors="replace").strip()[:120]
            except OSError:
                command = "?"
            result.append((percent, pid, command))
    return sorted(result, reverse=True)


def check_system_load(context):
    processes = busy_processes()
    busy_cpu = sum(p[0] for p in processes)
    if busy_cpu > BUSY_CPU_THRESHOLD:
        load = ", ".join(f"{l:.2f}" for l in os.getloadavg())
        print(f"WARNING ({context}): other processes use {busy_cpu:.0f}% CPU (load average {load}) - "
              f"timings are unreliable:", file=sys.stderr)
        for percent, pid, command in processes[:5]:
            print(f"  {percent:6.1f}%  pid {pid}  {command}", file=sys.stderr)
    return busy_cpu


def ratio(entry, numerator, denominator, suffix):
    a, b = entry.get(f"{numerator}{suffix}_s"), entry.get(f"{denominator}{suffix}_s")
    if a and b:
        entry[f"{numerator}_over_{denominator}{suffix}"] = f"{float(a) / float(b):.2f}"


check_system_load("start")
rows = []
names = sorted({f.rsplit(".", 2)[0] for f in os.listdir(QUERY_DIR) if f.endswith(".sql")})
for name in names:
    entry = {"query": name, "busy_cpu": f"{check_system_load(name):.0f}"}
    for variant in VARIANTS:
        path = os.path.join(QUERY_DIR, f"{name}.{variant}.sql")
        if not os.path.exists(path):
            continue
        sql = open(path).read()
        failed = set()
        for config in CONFIGS:
            seconds, error = run_timed(sql, config["path"], config["threads"])
            entry[f"{variant}{config['suffix']}_s"] = "" if seconds is None else f"{seconds[0]:.4f}"
            entry[f"{variant}{config['suffix']}_cpu"] = "" if seconds is None else f"{seconds[1]:.4f}"
            if seconds is None:
                entry[f"{variant}{config['suffix']}_error"] = error if isinstance(error, str) else " ".join(error)
                failed.add(config["label"])
        for label, binary in BINARIES:
            key = f"{variant}{'_' + label if len(BINARIES) > 1 else ''}_result"
            entry[key] = "n/a" if label in failed else result_hash(sql, binary)
    oracle_results = {}
    for variant in VARIANTS[1:]:
        oracle_path = os.path.join(QUERY_DIR, f"{name}.{variant}.oracle")
        for label, _ in BINARIES:
            binary_suffix = "_" + label if len(BINARIES) > 1 else ""
            result = entry.get(f"{variant}{binary_suffix}_result")
            if result is None:
                continue
            if os.path.exists(oracle_path):
                if oracle_path not in oracle_results:
                    oracle_results[oracle_path] = result_hash(open(oracle_path).read())
                expected, reference = oracle_results[oracle_path], "oracle"
            else:
                expected, reference = entry.get(f"builtin{binary_suffix}_result"), "builtin"
            entry[f"{variant}{binary_suffix}_ok"] = str(expected == result)
            entry[f"{variant}_reference"] = reference
    for config in CONFIGS:
        ratio(entry, "builtin", "node", config["suffix"])
        ratio(entry, "node", "split", config["suffix"])
        for variant in ("flat", "flat_umbra", "flat_minmax"):
            ratio(entry, variant, "node", config["suffix"])
    rows.append(entry)
    print(entry, flush=True)

fields = list(dict.fromkeys(key for row in rows for key in row))
with open(OUT_CSV, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
