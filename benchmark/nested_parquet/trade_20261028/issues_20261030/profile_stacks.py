#!/usr/bin/env python3
"""Where a query spends its CPU time, from perf samples with call stacks (issue 1).

The query runs twice in one CLI process. perf starts with its events disabled; the CLI switches them on right before
the second run and off right after it (.shell, through perf's control fifo), so only the measured run is sampled.
Every sample carries its user stack (--call-graph dwarf: the release build has no frame pointers), which
categories.py walks from the sampled function upwards - memcpy, malloc, the kernel, validity and vector helpers count
for the code that called them.

Written next to OUT (a path prefix):
  OUT.folded.gz  the stacks ('root;...;leaf count', frames 'function@dso'), re-classifiable with categories.py
  OUT.txt        wall and CPU time, CPU ms per category and sub-category, the hottest functions of every category,
                 and for the functions in WATCH the callers they were reached from
CSV_OUT gets one row per category and sub-category: label, wall ms, CPU ms of the run, category, sub, CPU ms.

PERF is the perf command ("sudo perf" where perf_event_paranoid keeps users from sampling); SETUP is SQL run before
both runs (e.g. SET parquet_prenest_auto = false).

Usage: [THREADS=1] [FREQ=1000] [STACK=16384] [PERF=perf] [SETUP=sql] [CSV_OUT=csv LABEL=name] [WATCH=f1,f2]
       profile_stacks.py <duckdb binary> <data dir> <query file> <OUT prefix>
"""
import collections
import gzip
import itertools
import os
import re
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from categories import CATEGORIES, classify, function_name  # noqa: E402

DUCKDB, DATA_DIR, QUERY_FILE, OUT = sys.argv[1:5]
THREADS = os.environ.get("THREADS", "1")
FREQ = int(os.environ.get("FREQ", "1000"))
STACK = os.environ.get("STACK", "16384")
PERF = shlex.split(os.environ.get("PERF", "perf"))
SETUP = os.environ.get("SETUP", "")
WATCH = [
    w
    for w in os.environ.get(
        "WATCH",
        "VectorStringBuffer::CopyInternal,TemplatedValidityMask<unsigned long>::SetInvalid,ValidityMask::CopySel,"
        "VectorBuffer::Copy,SelectionVector::Slice",
    ).split(",")
    if w
]


def record(tmp):
    query = open(QUERY_FILE).read().strip().rstrip(";")
    ctl, ack, toggle = (os.path.join(tmp, name) for name in ("ctl", "ack", "toggle.sh"))
    os.mkfifo(ctl)
    os.mkfifo(ack)
    with open(toggle, "w") as f:
        f.write(f'#!/bin/sh\necho "$1" > {ctl} && head -c 4 {ack} > /dev/null\n')
    os.chmod(toggle, 0o755)
    script = (
        f"SET threads = {THREADS};\n{SETUP}\n.mode trash\n{query};\n.timer on\n"
        f".shell {toggle} enable\n{query};\n.shell {toggle} disable\n"
    )
    data = os.path.join(tmp, "perf.data")
    run = subprocess.run(
        [*PERF, "record", "-q", "-F", str(FREQ), "--call-graph", f"dwarf,{STACK}", "-D", "-1",
         "--control", f"fifo:{ctl},{ack}", "-o", data, "--", DUCKDB, "-no-agent"],
        input=script, text=True, cwd=DATA_DIR, capture_output=True,
    )
    timings = re.findall(r"Run Time \(s\): real ([0-9.]+)", run.stdout + run.stderr)
    if run.returncode or not timings:
        sys.exit(f"perf record failed ({run.returncode}): {(run.stderr or run.stdout).strip()[-500:]}")
    if PERF[0] == "sudo":
        subprocess.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", data], check=True)
    return float(timings[-1]), data


def parse(data):
    """[(stack from the leaf: [(function, dso)])] of the DuckDB process's samples (not of the toggle script's)."""
    samples, stack = [], None
    comm = os.path.basename(DUCKDB)[:15]
    script = subprocess.Popen(["perf", "script", "-i", data, "-F", "comm,tid,time,ip,sym,dso"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True)
    for line in itertools.chain(script.stdout, [""]):
        line = line.rstrip("\n")
        if line.startswith("\t"):
            m = re.match(r"\s*[0-9a-f]+ (.*) \((.*)\)$", line)
            if stack is not None and m:
                name = function_name(re.sub(r"\+0x[0-9a-f]+$", "", m.group(1)))
                stack.append((sys.intern(name), sys.intern(os.path.basename(m.group(2)))))
            continue
        if stack:
            samples.append(stack)
        stack = [] if line.split()[:1] == [comm] else None
    if script.wait():
        sys.exit(f"perf script failed ({script.returncode})")
    return samples


def main():
    # perf.data next to the results: /tmp may be small
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(OUT))) as tmp:
        wall, data = record(tmp)
        samples = parse(data)
    cpu_ms = len(samples) * 1000 / FREQ
    label = os.environ.get("LABEL", os.path.basename(OUT))

    folded = collections.Counter(";".join(f"{f}@{d}" for f, d in reversed(stack)) for stack in samples)
    with gzip.open(OUT + ".folded.gz", "wt") as f:
        f.write(f"# freq={FREQ} wall_ms={wall * 1000:.1f} label={label.replace(' ', '_')}\n")
        for frames, n in folded.most_common():
            f.write(f"{frames} {n}\n")

    per_sub = collections.Counter()
    hottest = collections.defaultdict(collections.Counter)
    callers = collections.defaultdict(collections.Counter)
    for stack in samples:
        category, sub = classify(stack)
        per_sub[(category, sub)] += 1
        hottest[category][stack[0][0]] += 1
        for i, (frame, _) in enumerate(stack):
            hit = next((w for w in WATCH if frame.endswith(w)), None)
            if hit:
                chain = " < ".join(name.replace("duckdb::", "")[:70] for name, _ in stack[i + 1 : i + 4])
                callers[hit][(f"{category}/{sub}", chain)] += 1
                break
    per_category = collections.Counter()
    for (category, _), n in per_sub.items():
        per_category[category] += n

    ms = lambda n: n * 1000 / FREQ  # noqa: E731
    depths = sorted(len(stack) for stack in samples) or [0]
    lines = [
        f"{label}: threads={THREADS} wall {wall * 1000:.0f} ms, CPU {cpu_ms:.0f} ms ({len(samples)} samples, {FREQ} Hz)",
        # a median of 1-2 frames means perf could not unwind the stacks (no dwarf support): categories by leaf only
        f"stack depth: median {depths[len(depths) // 2]} frames, {100 * sum(d < 3 for d in depths) / len(depths):.0f}% "
        f"of the samples with fewer than 3",
    ]
    lines.append("CPU ms per category (sub-categories in brackets):")
    for category in CATEGORIES:
        if per_category[category]:
            subs = ", ".join(f"{s} {ms(n):.0f}" for (c, s), n in per_sub.most_common() if c == category)
            lines.append(f"  {category:8} {ms(per_category[category]):8.0f}  {100 * per_category[category] / len(samples):5.1f}%  [{subs}]")
    lines.append("hottest sampled functions per category:")
    for category in CATEGORIES:
        for function, n in hottest[category].most_common(5 if category != "기타" else 8):
            lines.append(f"  {category:8} {ms(n):7.0f} ms  {function[:110]}")
    if callers:
        lines.append("callers of the watched functions (category of the sample / the next three frames up):")
        for watched, chains in callers.items():
            lines.append(f"  {watched}: {ms(sum(chains.values())):.0f} ms")
            for (where, chain), n in chains.most_common(6):
                lines.append(f"    {ms(n):6.0f} ms  {where}  < {chain}")
    text = "\n".join(lines)
    with open(OUT + ".txt", "w") as f:
        f.write(text + "\n")
    print(text)
    if os.environ.get("CSV_OUT"):
        with open(os.environ["CSV_OUT"], "a") as f:
            for (category, sub), n in per_sub.most_common():
                f.write(f"{label},{wall * 1000:.1f},{cpu_ms:.1f},{category},{sub},{ms(n):.1f}\n")


if __name__ == "__main__":
    main()
