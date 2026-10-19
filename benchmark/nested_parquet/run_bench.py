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
A binary can be given setup statements, run before every query of its configuration (and of its result check):
label=path;SET a = 1;SET b = 2 - they must not contain commas. The setup of every configuration is recorded in the
setup_<label> columns.

VARIANTS limits the variants a configuration runs, per label: VARIANTS="base=builtin final=flat,flat_minmax" runs
only the builtin queries with the binary "base" and only the flat ones with "final" (labels not listed run all
variants). A variant is then checked against the builtin result of another binary when its own binary does not run
the builtin query.

With SKIPS=1, every node and flat query is run once more with debug logging, and the tasks that the read_parquet_node
scans skipped are recorded as <variant>_<suffix>_skipped: "<by the query's filters>+<by join filters>/<tasks>", summed
over the scans of the query.

Before the first query the CPU use of the other processes is sampled three times: when they keep more than half a core
busy in every sample (a leftover query, a search running in the background), the benchmark does not start - it lists
them and exits with status 2 (ALLOW_BUSY=1 starts it anyway). Before every query the CPU use is sampled again; a
warning is printed when it is high, and it is recorded in the busy_cpu column, as the load distorts the timings.

Every DuckDB process runs in a process group of its own, which is killed when it exceeds QUERY_TIMEOUT and when the
benchmark itself is interrupted or terminated - so that no query keeps running after the benchmark and loads the
machine during later measurements.

The CSV is written to <result csv>.partial after every query and renamed to <result csv> when all queries are done.

Usage: [RUNS=n] [THREADS=n[,n...]] [VARIANTS="label=v,v ..."] [SKIPS=1] [ALLOW_BUSY=1] run_bench.py <duckdb binary | label=path,...> <query dir> <data dir> <result csv>
"""
import csv
import os
import re
import signal
import subprocess
import sys
import time

QUERY_DIR = sys.argv[2]
DATA_DIR = sys.argv[3]
OUT_CSV = sys.argv[4]
RUNS = int(os.environ.get("RUNS", "5"))
TIMEOUT = int(os.environ.get("QUERY_TIMEOUT", "600"))

SKIPS = os.environ.get("SKIPS", "") == "1"

BINARIES = []
for entry in sys.argv[1].split(","):
    binary, *setup = entry.split(";")
    label, _, path = binary.partition("=") if "=" in binary.split("/")[0] else ("", "", binary)
    BINARIES.append((label or "duckdb", path, "".join(statement.strip() + ";\n" for statement in setup)))
THREADS = [t for t in os.environ.get("THREADS", "").split(",") if t] or [None]
CONFIGS = []
for label, path, setup in BINARIES:
    for threads in THREADS:
        parts = ([label] if len(BINARIES) > 1 else []) + ([f"t{threads}"] if len(THREADS) > 1 else [])
        CONFIGS.append(
            {
                "label": label,
                "path": path,
                "threads": threads,
                "setup": setup,
                "suffix": "".join("_" + part for part in parts),
            }
        )
DUCKDB = BINARIES[0][1]
LABEL_VARIANTS = {}
for item in os.environ.get("VARIANTS", "").split():
    label, _, variants = item.partition("=")
    LABEL_VARIANTS[label] = set(variants.split(","))


def runs_variant(label, variant):
    return label not in LABEL_VARIANTS or variant in LABEL_VARIANTS[label]


#: The process groups of the DuckDB processes that are running, killed when the benchmark stops
RUNNING_GROUPS = set()


def run_process(args, input=None, timeout=None):
    """Like subprocess.run(capture_output=True, text=True, cwd=DATA_DIR), in a process group of its own that is killed
    on a timeout - with everything the process started."""
    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=DATA_DIR,
        start_new_session=True,
    )
    RUNNING_GROUPS.add(proc.pid)
    try:
        stdout, stderr = proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc.pid)
        proc.communicate()
        raise
    finally:
        RUNNING_GROUPS.discard(proc.pid)
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def kill_group(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def stop(signum, frame):
    for pgid in list(RUNNING_GROUPS):
        kill_group(pgid)
    sys.exit(128 + signum)


for stop_signal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(stop_signal, stop)


def run_timed(sql, binary, threads, config_setup=""):
    setup = (f"SET threads = {threads};\n" if threads else "") + config_setup
    script = setup + ".timer on\n.mode trash\n" + "\n".join([sql.strip().rstrip(";") + ";"] * RUNS) + "\n"
    try:
        proc = run_process([binary, "-no-agent"], input=script, timeout=TIMEOUT * RUNS)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    timings = re.findall(r"Run Time \(s\): real ([0-9.]+) user ([0-9.]+) sys ([0-9.]+)", proc.stdout + proc.stderr)
    if proc.returncode != 0 or len(timings) != RUNS:
        return None, (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["error"]
    wall = min(float(real) for real, _, _ in timings)
    cpu = min(float(user) + float(sys) for _, user, sys in timings)
    return (wall, cpu), ""


def result_hash(sql, binary=None, setup=""):
    # order-insensitive fingerprint of the result, with numbers rounded to absorb float summation order
    inner = sql.strip().rstrip(";")
    query = (
        "SELECT count(*), hash(list(r ORDER BY r)) FROM (SELECT list_transform(list_value(COLUMNS(*)::VARCHAR), "
        "lambda x: CASE WHEN TRY_CAST(x AS DOUBLE) IS NULL THEN x ELSE round(x::DOUBLE, 2)::VARCHAR END)::VARCHAR AS r "
        f"FROM ({inner}))"
    )
    try:
        proc = run_process([binary or DUCKDB, "-no-agent", "-csv", "-noheader", "-c", setup + query], timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "error: timeout"
    return proc.stdout.strip() if proc.returncode == 0 else "error: " + proc.stderr.strip()[-200:]


SKIP_MESSAGE = re.compile(r"skip (\d+) of (\d+) tasks of node[^,]*(?:, the filters of joins (\d+) more)?")


def skipped_tasks(sql, binary, threads, config_setup):
    """The tasks the read_parquet_node scans of a query skipped: by the query's filters, by join filters, of all."""
    setup = (f"SET threads = {threads};\n" if threads else "") + config_setup
    script = (
        setup
        + "CALL enable_logging(level := 'debug', storage := 'memory');\n.mode trash\n"
        + sql.strip().rstrip(";")
        + ";\n.mode list\n.headers off\n"
        "SELECT message FROM duckdb_logs WHERE message LIKE 'read_parquet_node: the filters%';\n"
    )
    try:
        proc = run_process([binary, "-no-agent"], input=script, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "timeout"
    by_query = by_join = tasks = 0
    for match in SKIP_MESSAGE.finditer(proc.stdout):
        by_query += int(match.group(1))
        tasks += int(match.group(2))
        by_join += int(match.group(3) or 0)
    return f"{by_query}+{by_join}/{tasks}"


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
        print(
            f"WARNING ({context}): other processes use {busy_cpu:.0f}% CPU (load average {load}) - "
            f"timings are unreliable:",
            file=sys.stderr,
        )
        for percent, pid, command in processes[:5]:
            print(f"  {percent:6.1f}%  pid {pid}  {command}", file=sys.stderr)
    return busy_cpu


def require_idle_system():
    """Exit when other processes keep the CPU busy in every one of three samples - a spike does not stop the start."""
    samples = [busy_processes(interval=1.0) for _ in range(3)]
    busy = [sum(p[0] for p in processes) for processes in samples]
    if min(busy) <= BUSY_CPU_THRESHOLD:
        return
    print(
        f"ERROR: other processes use {min(busy):.0f}-{max(busy):.0f}% CPU (threshold {BUSY_CPU_THRESHOLD:.0f}%) - "
        f"not starting the benchmark. Stop them, or set ALLOW_BUSY=1:",
        file=sys.stderr,
    )
    for percent, pid, command in samples[-1][:5]:
        print(f"  {percent:6.1f}%  pid {pid}  {command}", file=sys.stderr)
    sys.exit(2)


def ratio(entry, numerator, denominator, suffix):
    a, b = entry.get(f"{numerator}{suffix}_s"), entry.get(f"{denominator}{suffix}_s")
    if a and b:
        entry[f"{numerator}_over_{denominator}{suffix}"] = f"{float(a) / float(b):.2f}"


if os.environ.get("ALLOW_BUSY", "") != "1":
    require_idle_system()
check_system_load("start")
rows = []
names = sorted({f.rsplit(".", 2)[0] for f in os.listdir(QUERY_DIR) if f.endswith(".sql")})
for name in names:
    entry = {"query": name, "busy_cpu": f"{check_system_load(name):.0f}"}
    for label, _, setup in BINARIES:
        if setup:
            entry[f"setup_{label}"] = setup.replace("\n", " ").strip()
    for variant in VARIANTS:
        path = os.path.join(QUERY_DIR, f"{name}.{variant}.sql")
        if not os.path.exists(path):
            continue
        sql = open(path).read()
        failed = set()
        for config in CONFIGS:
            if not runs_variant(config["label"], variant):
                continue
            seconds, error = run_timed(sql, config["path"], config["threads"], config["setup"])
            entry[f"{variant}{config['suffix']}_s"] = "" if seconds is None else f"{seconds[0]:.4f}"
            entry[f"{variant}{config['suffix']}_cpu"] = "" if seconds is None else f"{seconds[1]:.4f}"
            if seconds is None:
                entry[f"{variant}{config['suffix']}_error"] = error if isinstance(error, str) else " ".join(error)
                failed.add(config["label"])
            elif SKIPS and variant.startswith(("node", "flat")):
                entry[f"{variant}{config['suffix']}_skipped"] = skipped_tasks(
                    sql, config["path"], config["threads"], config["setup"]
                )
        for label, binary, setup in BINARIES:
            if not runs_variant(label, variant):
                continue
            key = f"{variant}{'_' + label if len(BINARIES) > 1 else ''}_result"
            entry[key] = "n/a" if label in failed else result_hash(sql, binary, setup)
    oracle_results = {}
    for variant in VARIANTS[1:]:
        oracle_path = os.path.join(QUERY_DIR, f"{name}.{variant}.oracle")
        for label, _, _ in BINARIES:
            binary_suffix = "_" + label if len(BINARIES) > 1 else ""
            result = entry.get(f"{variant}{binary_suffix}_result")
            if result is None:
                continue
            if os.path.exists(oracle_path):
                if oracle_path not in oracle_results:
                    oracle_results[oracle_path] = result_hash(open(oracle_path).read())
                expected, reference = oracle_results[oracle_path], "oracle"
            elif f"builtin{binary_suffix}_result" in entry:
                expected, reference = entry[f"builtin{binary_suffix}_result"], "builtin"
            else:
                # the binary does not run the builtin query: the builtin result of another binary
                others = [l for l, _, _ in BINARIES if f"builtin_{l}_result" in entry]
                expected = entry[f"builtin_{others[0]}_result"] if others else None
                reference = f"builtin of {others[0]}" if others else "none"
            ok = expected is not None and expected == result and not result.startswith(("error", "n/a"))
            entry[f"{variant}{binary_suffix}_ok"] = str(ok)
            entry[f"{variant}_reference"] = reference
    for config in CONFIGS:
        ratio(entry, "builtin", "node", config["suffix"])
        ratio(entry, "node", "split", config["suffix"])
        for variant in ("flat", "flat_umbra", "flat_minmax"):
            ratio(entry, variant, "node", config["suffix"])
    rows.append(entry)
    print(entry, flush=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with open(OUT_CSV + ".partial", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

os.replace(OUT_CSV + ".partial", OUT_CSV)
