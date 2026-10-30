#!/usr/bin/env python3
"""Time query files in the five configurations and check their results (issues 1-1 and 2-1).

A query directory holds <name>.<variant>.sql: base, prenestoff and prenest run the builtin files, flat (main_rey)
the flat ones, pure flat (base) the split ones. Leading SET lines of a file are setup: they run before the timer,
like the configuration's own setup. Every (name, configuration) runs RUNS times in one CLI process at THREADS; the
fastest wall-clock time and the smallest CPU time (user + sys) are kept, as in ../../run_bench.py.

Results: every run's rows are compared with the reference - the base builtin result of <name> with its first dotted
part kept and ".orig" appended when such a file exists (q7_plots.fixed -> q7_plots.orig), else of <name> itself.
Integers and strings exactly, floats to a relative 1e-9, rows sorted (the comparison of run_bench.py).

With PLAN_DIR, the EXPLAIN ANALYZE plan of every timed (name, configuration) is written to
PLAN_DIR/<name>.<configuration>.txt (plans.py: build/probe sides, estimated and actual rows per operator) - one more
run of the query.

With SAME_PLAN=1 a configuration's file whose physical plan (operators, build/probe sides, files and nodes - not the
estimates) equals the plan of its reference name's file in the same configuration is not timed again: the row
records "same plan as <reference>" and copies the reference's time.

Before the first query the CPU use of the other processes is sampled; the run does not start when more than half a
core is busy (ALLOW_BUSY=1 starts anyway). The busy cores before every query are recorded.

Usage: [RUNS=10] [THREADS=1] [CONFIGS="base prenestoff prenest flat pureflat"] [SAME_PLAN=1] [ALLOW_BUSY=1]
       [QUERY_TIMEOUT=7200] [PLAN_DIR=dir] time_queries.py <query dir> <data dir> <out csv> [name ...]
Environment: BASE, PRENEST, FINAL (binaries, default ~/nested-bench/...)
"""
import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plans import explain_analyze, tree_text  # noqa: E402

NB = os.path.expanduser("~/nested-bench")
BASE = os.environ.get("BASE", f"{NB}/duckdb_base/build/release/duckdb")
PRENEST = os.environ.get("PRENEST", f"{NB}/duckdb_prenest_base/build/release/duckdb")
FINAL = os.environ.get("FINAL", f"{NB}/duckdb_rey/build/release/duckdb")
ALL_CONFIGS = {  # label: binary, setup, variant
    "base": (BASE, "", "builtin"),
    "prenestoff": (PRENEST, "SET parquet_prenest_auto = false;", "builtin"),
    "prenest": (PRENEST, "SET parquet_prenest_auto = true;", "builtin"),
    "flat": (FINAL, "", "flat"),
    "pureflat": (BASE, "", "split"),
}
RUNS = int(os.environ.get("RUNS", "10"))
THREADS = os.environ.get("THREADS", "1")
TIMEOUT = int(os.environ.get("QUERY_TIMEOUT", "7200"))
REL_TOL = 1e-9


def read_query(path):
    """(setup: the leading SET lines, query)"""
    setup, rest = [], []
    for line in open(path).read().strip().splitlines():
        if not rest and line.strip().upper().startswith("SET "):
            setup.append(line.strip())
        else:
            rest.append(line)
    return "\n".join(setup) + ("\n" if setup else ""), "\n".join(rest).strip().rstrip(";")


def duckdb(binary, script, args=(), timeout=TIMEOUT):
    proc = subprocess.run(
        [binary, "-no-agent", *args], input=script, text=True, capture_output=True, cwd=DATA, timeout=timeout
    )
    return proc.returncode, proc.stdout, proc.stderr


def parse_value(text):
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    if re.fullmatch(r"-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?|-?inf|nan", text):
        return float(text)
    return text


def sort_key(row):
    return tuple((1, v) if isinstance(v, str) else (0, float(f"{v:.6g}") if isinstance(v, float) else v) for v in row)


def same_rows(a, b):
    if isinstance(a, str) or isinstance(b, str) or len(a) != len(b):
        return False
    for row_a, row_b in zip(a, b):
        if len(row_a) != len(row_b):
            return False
        for x, y in zip(row_a, row_b):
            if isinstance(x, float) or isinstance(y, float):
                if isinstance(x, str) or isinstance(y, str):
                    return False
                if not (math.isclose(x, y, rel_tol=REL_TOL) or (math.isnan(x) and math.isnan(y))):
                    return False
            elif x != y:
                return False
    return True


def result_rows(binary, setup, query):
    code, out, err = duckdb(binary, f"SET threads = {THREADS};\n{setup}{query};\n", ("-csv", "-noheader"))
    if code or err.strip():
        return "error: " + (err.strip() or f"exit {code}")[-200:]
    rows = [tuple(parse_value(v) for v in row) for row in csv.reader(io.StringIO(out))]
    return sorted(rows, key=sort_key)


def fingerprint(rows):
    if isinstance(rows, str):
        return rows
    text = "\n".join(",".join(f"{v:.9g}" if isinstance(v, float) else str(v) for v in row) for row in rows)
    return f"{len(rows)},{hashlib.sha1(text.encode()).hexdigest()[:16]}"


def plan_signature(binary, setup, query):
    """The physical plan without estimates: operator, extra info naming files, nodes, conditions, children."""
    code, out, err = duckdb(binary, f"SET threads = {THREADS};\n{setup}EXPLAIN (FORMAT json) {query};\n", ("-list", "-noheader"))
    if code or "[" not in out:
        return "error"
    plan = json.loads(out[out.index("[") : out.rindex("]") + 1])

    def walk(node):
        extra = node.get("extra_info", {})
        keep = {k: v for k, v in extra.items() if k in ("Table", "File", "Node", "Conditions", "Join Type", "Groups")}
        return [node["name"], keep, [walk(c) for c in node.get("children", [])]]

    return hashlib.sha1(json.dumps([walk(n) for n in plan], sort_keys=True).encode()).hexdigest()[:16]


def run_timed(binary, setup, query):
    script = f"SET threads = {THREADS};\n{setup}.timer on\n.mode trash\n" + f"{query};\n" * RUNS
    try:
        code, out, err = duckdb(binary, script, timeout=TIMEOUT * RUNS)
    except subprocess.TimeoutExpired:
        return None, None, "timeout"
    timings = re.findall(r"Run Time \(s\): real ([0-9.]+) user ([0-9.]+) sys ([0-9.]+)", out + err)
    if code or len(timings) != RUNS:
        return None, None, ((err or out).strip().splitlines() or ["error"])[-1][:200]
    return min(float(r) for r, _, _ in timings), min(float(u) + float(s) for _, u, s in timings), ""


def cpu_ticks():
    with open("/proc/stat") as f:
        fields = [int(x) for x in f.readline().split()[1:]]
    return sum(fields) - fields[3] - fields[4], sum(fields)


def busy_cores(interval=1.0):
    busy0, total0 = cpu_ticks()
    time.sleep(interval)
    busy1, total1 = cpu_ticks()
    return (busy1 - busy0) / max(total1 - total0, 1) * os.cpu_count()


def reference_name(name):
    base = name.split(".")[0] + ".orig"
    return base if os.path.exists(os.path.join(QUERY_DIR, f"{base}.builtin.sql")) else name


QUERY_DIR = DATA = None


def main():
    global QUERY_DIR, DATA
    QUERY_DIR, DATA, out_csv = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    configs = os.environ.get("CONFIGS", " ".join(ALL_CONFIGS)).split()
    names = sys.argv[4:] or {f.rsplit(".", 2)[0] for f in os.listdir(QUERY_DIR) if f.endswith(".sql")}
    # a reference before the names compared with it
    names = sorted(names, key=lambda n: (n.split(".")[0], reference_name(n) != n, n))
    if os.environ.get("ALLOW_BUSY") != "1":
        busy = min(busy_cores() for _ in range(3))
        if busy > 0.5:
            sys.exit(f"other processes keep {busy:.1f} cores busy - not starting (ALLOW_BUSY=1 starts anyway)")
    references, plans, timings = {}, {}, {}
    fields = ["name", "config", "wall_s", "cpu_s", "runs", "threads", "same_result", "result", "plan", "note", "busy_cores"]
    with open(out_csv + ".partial", "w", newline="") as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        for name in names:
            for config in configs:
                binary, config_setup, variant = ALL_CONFIGS[config]
                path = os.path.join(QUERY_DIR, f"{name}.{variant}.sql")
                if not os.path.exists(path):
                    continue
                file_setup, query = read_query(path)
                setup = config_setup + "\n" + file_setup
                ref = reference_name(name)
                if ref not in references:
                    ref_setup, ref_query = read_query(os.path.join(QUERY_DIR, f"{ref}.builtin.sql"))
                    references[ref] = result_rows(BASE, ref_setup, ref_query)
                row = {"name": name, "config": config, "runs": RUNS, "threads": THREADS, "note": ""}
                rows = result_rows(binary, setup, query)
                row["result"] = fingerprint(rows)
                row["same_result"] = "yes" if same_rows(rows, references[ref]) else "NO"
                plan = plans[(name, config)] = plan_signature(binary, setup, query)
                row["plan"] = plan
                if os.environ.get("SAME_PLAN") == "1" and ref != name and plans.get((ref, config)) == plan:
                    row["wall_s"], row["cpu_s"] = timings.get((ref, config), ("", ""))
                    row["note"] = f"same plan as {ref}"
                else:
                    row["busy_cores"] = f"{busy_cores(0.5):.1f}"
                    wall, cpu, error = run_timed(binary, setup, query)
                    row["wall_s"], row["cpu_s"] = (f"{wall:.3f}", f"{cpu:.3f}") if wall is not None else ("", "")
                    row["note"] = error
                    timings[(name, config)] = (row["wall_s"], row["cpu_s"])
                    if os.environ.get("PLAN_DIR"):
                        os.makedirs(os.environ["PLAN_DIR"], exist_ok=True)
                        try:
                            text = tree_text(explain_analyze(binary, DATA, setup, query, THREADS, TIMEOUT))
                        except (RuntimeError, subprocess.TimeoutExpired) as e:
                            text = f"error: {e}"
                        with open(os.path.join(os.environ["PLAN_DIR"], f"{name}.{config}.txt"), "w") as p:
                            p.write(text + "\n")
                writer.writerow(row)
                f.flush()
                print(
                    f"{name:22} {config:10} {row['wall_s']:>9} s  result {row['same_result']:3}  {row['note']}",
                    flush=True,
                )
    os.replace(out_csv + ".partial", out_csv)


if __name__ == "__main__":
    main()
