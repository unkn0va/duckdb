#!/usr/bin/env python3
"""Break down where a query spends its time, by sampling all its threads with perf (Linux).

perf only records the sampled instruction of every thread (no call stacks, which need a perf built with libdw); the
instruction is mapped to its function with the symbol table of the binary (nm) and the function to a category
(decoding Parquet, keys, hash join, aggregate, expressions, ...). The query runs twice in one CLI process; only the
samples of the second run count - the wall-clock time .timer reports for it, back from its last sample. The first run
warms up the caches.

Reported: CPU milliseconds per category, the hottest functions, and a timeline of the number of busy threads and what
they do, in buckets of BUCKET_MS - phases in which few threads are busy limit the speedup of more threads. The scan
splits into "list assembly" (the list and struct readers that build nested vectors from the levels), "pre-nest filter"
(prenest-3way's element predicate, applied during the assembly) and the decoding of the values ("parquet decode",
"parquet levels/skip", "scan filters / late decoding").

PERF is the perf command, e.g. "sudo perf" where perf_event_paranoid keeps users from sampling; the perf.data of a
sudo run is handed to the user (chown). SETUP is SQL run before the query (e.g. SET parquet_prenest_auto = true).
CSV_OUT appends one row per category (label, wall ms, category, CPU ms); LABEL names the run in it. PERF_DATA keeps
the perf.data at that path.

Usage: [THREADS=n] [FREQ=hz] [BUCKET_MS=ms] [PERF=perf] [SETUP=sql] [CSV_OUT=csv LABEL=name] [PERF_DATA=path]
       profile_breakdown.py <duckdb binary> <data dir> <query file>
"""
import bisect
import collections
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

DUCKDB, DATA_DIR, QUERY_FILE = sys.argv[1:4]
THREADS = os.environ.get("THREADS", "16")
FREQ = int(os.environ.get("FREQ", "4000"))
BUCKET_MS = float(os.environ.get("BUCKET_MS", "10"))
PERF = shlex.split(os.environ.get("PERF", "perf"))
SETUP = os.environ.get("SETUP", "")

# the first matching category of a function name wins
CATEGORIES = [
    ("pre-nest filter", ("PrenestFilter::Apply",)),
    ("list assembly", ("ListColumnReader", "StructColumnReader")),
    ("unnest", ("PhysicalUnnest", "UnnestOperator")),
    ("keys", ("ParquetNodeKeyGenerator",)),
    (
        "join filters",
        (
            "JoinFilterPushdown",
            "PrefixRange",
            "BloomFilter",
            "DynamicTableFilterSet",
            "SelectivityOptionalFilter",
            "PushDynamicFilters",
            "FinalizeFilters",
        ),
    ),
    (
        "scan filters / late decoding",
        (
            "FilterSelection",
            "FilterExecutor",
            "ExpressionFilter",
            "TableFilterState",
            "ColumnReader::Select",
            "DirectSelect",
            "PlainSelect",
            "FilterRows",
        ),
    ),
    ("parquet levels/skip", ("::Skip", "PlainSkip", "ReadLevels", "SkipPageValues", "ApplyPendingSkips")),
    (
        "parquet decode",
        (
            "ColumnReader",
            "Decoder",
            "RleBpDecoder",
            "snappy",
            "Snappy",
            "ZSTD",
            "duckdb_zstd",
            "thrift",
            "Thrift",
            "ParquetDecodeUtils",
            "BitpackingPrimitives",
            "ByteBuffer",
            "ResizeableBuffer",
            "miniz",
            "lz4",
            "duckdb_lz4",
            "brotli",
            "Callback",
        ),
    ),
    ("hash join", ("JoinHashTable", "PhysicalHashJoin", "ScanStructure", "JoinHT", "PerfectHashJoin")),
    (
        "aggregate",
        (
            "Aggregate",
            "Radix",
            "SumState",
            "AvgState",
            "CountStar",
            "TupleDataCollection",
            "TupleDataAllocator",
            "TupleDataLayout",
            "RowOperations",
            "Scatter",
            "Gather",
        ),
    ),
    ("hashing", ("VectorOperations::Hash", "HashOp", "CombineHash", "Murmur", "duckdb::Hash")),
    (
        "expressions",
        (
            "ExpressionExecutor",
            "BinaryExecutor",
            "UnaryExecutor",
            "Comparison",
            "Select",
            "LikeOperator",
            "Contains",
            "Cast",
            "VectorOperations",
            "BoundComparison",
            "Interval",
            "Date",
            "Timestamp",
            "Decimal",
        ),
    ),
    (
        "vectors",
        (
            "Vector::",
            "FlatVector",
            "ConstantVector",
            "DictionaryVector",
            "SelectionVector",
            "DataChunk",
            "ValidityMask",
            "StringVector",
            "VectorCache",
            "UnifiedVectorFormat",
        ),
    ),
    (
        "scheduler",
        (
            "TaskScheduler",
            "Executor",
            "Pipeline",
            "concurrentqueue",
            "ConcurrentQueue",
            "Semaphore",
            "LightweightSemaphore",
            "Task::",
            "ProducerToken",
        ),
    ),
]


def classify(function):
    for name, patterns in CATEGORIES:
        if any(p in function for p in patterns):
            return name
    return "other duckdb"


def load_symbols(binary):
    out = subprocess.run(
        ["nm", "-C", "--defined-only", "-n", binary], capture_output=True, text=True, check=True
    ).stdout
    addresses, names = [], []
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[1] in "tTwW":
            addresses.append(int(parts[0], 16))
            names.append(parts[2])
    return addresses, names


def record():
    query = open(QUERY_FILE).read().strip().rstrip(";")
    script = f"SET threads = {THREADS};\n{SETUP}\n{query};\n.timer on\n{query};\n"
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "perf.data")
        run = subprocess.run(
            [*PERF, "record", "-q", "-F", str(FREQ), "-o", data, "--", DUCKDB, "-no-agent"],
            input=script,
            text=True,
            cwd=DATA_DIR,
            check=True,
            capture_output=True,
        )
        real = float(re.findall(r"Run Time \(s\): real ([0-9.]+)", run.stdout + run.stderr)[-1])
        if PERF[0] == "sudo":
            subprocess.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", data], check=True)
        mmaps = subprocess.run(
            ["perf", "script", "-i", data, "--show-mmap-events"], capture_output=True, text=True
        ).stdout
        out = subprocess.run(
            ["perf", "script", "-i", data, "-F", "tid,time,ip,dso"], capture_output=True, text=True, check=True
        ).stdout
        if os.environ.get("PERF_DATA"):
            shutil.copy(data, os.environ["PERF_DATA"])
    binary = os.path.realpath(DUCKDB)
    base = None
    for line in mmaps.splitlines():
        m = re.search(r"\[0x([0-9a-f]+)\(0x[0-9a-f]+\) @ 0x([0-9a-f]+) .*r-xp (\S+)", line)
        if m and os.path.realpath(m.group(3)) == binary:
            base = int(m.group(1), 16) - int(m.group(2), 16)
    samples = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+([0-9.]+):\s+([0-9a-f]+)\s+\((.*)\)", line)
        if m:
            samples.append((float(m.group(2)), int(m.group(1)), int(m.group(3), 16), m.group(4)))
    return samples, base, binary, real


def main():
    samples, base, binary, real = record()
    addresses, names = load_symbols(binary)

    def function_of(ip, dso):
        if base is not None and os.path.realpath(dso) == binary:
            i = bisect.bisect_right(addresses, ip - base) - 1
            return names[i] if i >= 0 else "?"
        return os.path.basename(dso)

    measured = []
    for t, tid, ip, dso in samples:
        function = function_of(ip, dso)
        if os.path.realpath(dso) == binary:
            category = classify(function)
        elif "libc" in dso or "libstdc++" in dso or "libm" in dso:
            category = "libc (memcpy/malloc/...)"
        elif "kernel" in dso:
            category = "kernel"
        else:
            category = "other"
        measured.append((t, tid, category, function))
    # the measured run is the last one: it ends with the last sample of a query operator, and took "real" seconds
    work = [s for s in measured if s[2] not in ("other", "kernel", "libc (memcpy/malloc/...)", "other duckdb")]
    end = max(s[0] for s in work)
    begin = end - real
    measured = [s for s in measured if begin <= s[0] <= end]
    wall = real
    cpu = len(measured) / FREQ
    print(
        f"threads={THREADS}  wall {wall * 1000:.0f} ms, CPU {cpu * 1000:.0f} ms, average busy threads "
        f"{cpu / wall if wall else 0:.1f}"
    )
    per_category = collections.Counter(s[2] for s in measured)
    print("  CPU ms per category:  " + ", ".join(f"{c} {n / FREQ * 1000:.0f}" for c, n in per_category.most_common()))
    if os.environ.get("CSV_OUT"):
        with open(os.environ["CSV_OUT"], "a") as f:
            for c, n in per_category.most_common():
                f.write(f"{os.environ.get('LABEL', QUERY_FILE)},{wall * 1000:.1f},{c},{n / FREQ * 1000:.1f}\n")
    top = collections.Counter(s[3] for s in measured).most_common(8)
    print("  hottest functions:")
    for function, n in top:
        print(f"    {n / FREQ * 1000:6.0f} ms  {function[:110]}")
    print(f"  timeline ({BUCKET_MS:.0f} ms): busy threads | main categories")
    buckets = collections.defaultdict(list)
    for t, _, c, _ in measured:
        buckets[int((t - begin) * 1000 / BUCKET_MS)].append(c)
    for b in range(int(wall * 1000 / BUCKET_MS) + 1):
        entries = buckets.get(b, [])
        busy = len(entries) / FREQ / (BUCKET_MS / 1000)
        main = ", ".join(
            f"{c} {n * 100 // max(len(entries), 1)}%" for c, n in collections.Counter(entries).most_common(3)
        )
        print(f"    {b * BUCKET_MS:5.0f} {busy:5.1f} | {main}")


if __name__ == "__main__":
    main()
