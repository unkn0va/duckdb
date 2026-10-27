#!/usr/bin/env python3
"""Benchmark nested Parquet queries with a cold OS page cache, one DuckDB process per run.

Before every run, the Parquet files the query names are evicted from the page cache with
posix_fadvise(POSIX_FADV_DONTNEED) - no root needed, and the page cache of other users' files is left alone - and
mincore() checks how much of them is still resident (column resident_pct: the most of any file; it should be near 0).
Each run starts a new CLI process, so DuckDB keeps nothing from the previous run either. The time is the query's own
"Run Time" of the CLI (.timer on), without process startup; read_mb is the data read from the block devices by the
process (/usr/bin/time %I, 512-byte blocks), which shows how much a configuration reads.

The configurations run interleaved - for every query, run 1 of every configuration, then run 2, ... - in an order that
rotates per run, so that no configuration is always first after an eviction. RUNS runs each (default 5); the
summary reports the median and the quartiles, as cold runs vary more than warm ones.

Binaries, setups, THREADS and VARIANTS as in run_bench.py: label=path;SET a = 1,label=path and
VARIANTS="base=builtin final=flat,flat_minmax". Results are not compared here (run_bench.py does that).

Usage: [RUNS=n] [THREADS=n[,n...]] [VARIANTS="label=v,v ..."] run_cold.py <label=path,...> <query dir> <data dir>
       <result csv>
       run_cold.py --summary <result csv> [...]   prints Markdown tables of medians, quartiles and MB read
"""
import csv
import ctypes
import glob
import math
import mmap
import os
import re
import signal
import statistics
import subprocess
import sys
import tempfile

VARIANTS = ("builtin", "node", "split", "flat", "flat_umbra", "flat_minmax")
PARQUET = re.compile(r"""['"]([^'"]+\.parquet)['"]""")
FIELDS = ["query", "variant", "label", "threads", "run", "seconds", "cpu", "read_mb", "resident_pct", "load", "error"]

libc = ctypes.CDLL(None, use_errno=True)
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
PAGE = os.sysconf("SC_PAGE_SIZE")


def evict(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        # dirty pages are not evicted: write them back first (a no-op for files written long ago)
        os.fdatasync(fd)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)


def resident_fraction(path):
    """The fraction of the file's pages in the page cache (mincore does not read them in)."""
    size = os.path.getsize(path)
    if size == 0:
        return 0.0
    fd = os.open(path, os.O_RDONLY)
    try:
        addr = libc.mmap(None, size, mmap.PROT_READ, mmap.MAP_SHARED, fd, 0)
        if addr in (None, ctypes.c_void_p(-1).value):
            raise OSError(ctypes.get_errno(), "mmap failed")
        try:
            pages = (size + PAGE - 1) // PAGE
            vec = (ctypes.c_ubyte * pages)()
            if libc.mincore(addr, size, vec) != 0:
                raise OSError(ctypes.get_errno(), "mincore failed")
            return sum(v & 1 for v in vec) / pages
        finally:
            libc.munmap(addr, size)
    finally:
        os.close(fd)


def summary(paths):
    for path in paths:
        rows = list(csv.DictReader(open(path)))
        ok = [r for r in rows if not r["error"]]
        groups = {}
        for r in ok:
            groups.setdefault((r["query"], r["threads"], r["label"]), []).append(r)
        labels = list(dict.fromkeys(r["label"] for r in rows))
        threads = list(dict.fromkeys(r["threads"] for r in rows))
        queries = list(dict.fromkeys(r["query"] for r in rows))
        print(f"### {os.path.basename(path)[:-4]}\n")
        print("Seconds: median [quartile 1 - 3]; MB read from disk: median.\n")
        print("| query | threads | " + " | ".join(labels) + " | " + " | ".join(f"{l} MB" for l in labels) + " |")
        print("|---|---|" + "---|" * (2 * len(labels)))
        medians = {}
        for q in queries:
            for t in threads:
                cells, mbs = [], []
                for l in labels:
                    g = groups.get((q, t, l), [])
                    if not g:
                        cells.append("-")
                        mbs.append("-")
                        continue
                    s = sorted(float(r["seconds"]) for r in g)
                    q1, med, q3 = statistics.quantiles(s, n=4) if len(s) > 1 else (s[0], s[0], s[0])
                    med = statistics.median(s)
                    medians[(q, t, l)] = med
                    cells.append(f"{med:.3f} [{q1:.3f}-{q3:.3f}]")
                    mbs.append(f"{statistics.median(float(r['read_mb']) for r in g):.0f}")
                print(f"| {q} | {t} | " + " | ".join(cells) + " | " + " | ".join(mbs) + " |")
        print()
        base = labels[0]
        print(f"Geometric mean of the per-query ratios of the medians, {base} / configuration:\n")
        print("| threads | " + " | ".join(f"{base} / {l}" for l in labels[1:]) + " |")
        print("|---|" + "---|" * (len(labels) - 1))
        for t in threads:
            cells = []
            for l in labels[1:]:
                ratios = [medians[(q, t, base)] / medians[(q, t, l)] for q in queries
                          if (q, t, base) in medians and (q, t, l) in medians]
                cells.append(f"{math.exp(sum(map(math.log, ratios)) / len(ratios)):.2f}x" if ratios else "-")
            print(f"| {t} | " + " | ".join(cells) + " |")
        worst = max((float(r["resident_pct"]) for r in rows), default=0)
        errors = len(rows) - len(ok)
        print(f"\nMost of a file still cached after eviction: {worst:.1f}%. Failed runs: {errors}.\n")


if len(sys.argv) > 1 and sys.argv[1] == "--summary":
    summary(sys.argv[2:])
    sys.exit(0)

QUERY_DIR, DATA_DIR, OUT_CSV = sys.argv[2:5]
RUNS = int(os.environ.get("RUNS", "5"))
TIMEOUT = int(os.environ.get("QUERY_TIMEOUT", "600"))
THREADS = [t for t in os.environ.get("THREADS", "").split(",") if t] or [None]
TIME = "/usr/bin/time"

BINARIES = []
for entry in sys.argv[1].split(","):
    binary, *setup = entry.split(";")
    label, _, path = binary.partition("=")
    BINARIES.append((label, path, "".join(statement.strip() + ";\n" for statement in setup)))
LABEL_VARIANTS = {}
for item in os.environ.get("VARIANTS", "").split():
    label, _, variants = item.partition("=")
    LABEL_VARIANTS[label] = set(variants.split(","))


def shell_flags(binary):
    probe = subprocess.run([binary, "-no-agent", "-c", "SELECT 1"], capture_output=True, text=True, timeout=60)
    return ["-no-agent"] if probe.returncode == 0 else []


FLAGS = {path: shell_flags(path) for _, path, _ in BINARIES}
CURRENT = [None]


def stop(signum, frame):
    if CURRENT[0]:
        try:
            os.killpg(CURRENT[0], signal.SIGKILL)
        except ProcessLookupError:
            pass
    sys.exit(128 + signum)


for stop_signal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(stop_signal, stop)


def run_cold(sql, files, binary, setup, threads):
    """One run after evicting files: (seconds, cpu, MB read, % still cached before the run, error)."""
    for f in files:
        evict(f)
    resident = max(resident_fraction(f) for f in files) * 100 if files else 0.0
    script = (f"SET threads = {threads};\n" if threads else "") + setup + ".timer on\n.mode trash\n"
    script += sql.strip().rstrip(";") + ";\n"
    with tempfile.NamedTemporaryFile("r", suffix=".time") as tf:
        proc = subprocess.Popen([TIME, "-o", tf.name, "-f", "%I", binary, *FLAGS[binary]], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=DATA_DIR,
                                start_new_session=True)
        CURRENT[0] = proc.pid
        try:
            out, err = proc.communicate(script, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            return None, None, None, resident, "timeout"
        finally:
            CURRENT[0] = None
        blocks = tf.read().strip().splitlines()
    timing = re.findall(r"Run Time \(s\): real ([0-9.]+) user ([0-9.]+) sys ([0-9.]+)", out + err)
    if proc.returncode != 0 or len(timing) != 1:
        lines = (err or out).strip().splitlines() or ["error"]
        return None, None, None, resident, next((l for l in lines if "Error" in l), lines[-1])[:200]
    real, user, sys_ = (float(v) for v in timing[0])
    mb = int(blocks[-1]) * 512 / 1048576 if blocks and blocks[-1].isdigit() else float("nan")
    return real, user + sys_, mb, resident, ""


queries = {}
for path in sorted(glob.glob(os.path.join(QUERY_DIR, "*.sql"))):
    name, variant = os.path.basename(path)[:-4].rsplit(".", 1)
    if variant in VARIANTS:
        queries.setdefault(name, {})[variant] = open(path).read()

configs = []
for label, path, setup in BINARIES:
    for variant in VARIANTS:
        if label in LABEL_VARIANTS and variant not in LABEL_VARIANTS[label]:
            continue
        for threads in THREADS:
            configs.append((label, path, setup, variant, threads))

partial = OUT_CSV + ".partial"
with open(partial, "w", newline="") as out:
    writer = csv.DictWriter(out, fieldnames=FIELDS)
    writer.writeheader()
    for name, sqls in queries.items():
        todo = [c for c in configs if c[3] in sqls]
        if not todo:
            continue
        sql_files = {v: sorted({os.path.join(DATA_DIR, f) for f in PARQUET.findall(s)}) for v, s in sqls.items()}
        for run in range(RUNS):
            shift = run % len(todo)
            for label, path, setup, variant, threads in todo[shift:] + todo[:shift]:
                seconds, cpu, mb, resident, error = run_cold(sqls[variant], sql_files[variant], path, setup, threads)
                writer.writerow({"query": name, "variant": variant, "label": label, "threads": threads or "",
                                 "run": run + 1, "seconds": seconds if seconds is not None else "",
                                 "cpu": cpu if cpu is not None else "", "read_mb": mb if mb is not None else "",
                                 "resident_pct": f"{resident:.2f}", "load": os.getloadavg()[0], "error": error})
                out.flush()
                if error:
                    print(f"ERROR {name}.{variant} {label} t{threads}: {error}", file=sys.stderr)
        print(f"{name}: {RUNS} runs x {len(todo)} configurations", file=sys.stderr)
os.replace(partial, OUT_CSV)
