#!/usr/bin/env python3
"""Compare two binaries with hardware counters (SERVER.md, step 11).

perf: every query runs in one process per binary under `perf stat`, RUNS_PER_PROCESS times with 1 thread, the binaries
alternating, REPEAT times; the smallest count of every event is kept. Prints per query the instructions and cycles of
each binary and their ratios (second / first binary), and the instructions per cycle.
  perf_compare.py perf --binary a1=<duckdb> --binary b=<duckdb> --queries <queries dir> --data <data dir>
                  [--repeat 5] [--runs-per-process 3] [--events instructions:u,cycles:u] [--setup "<SQL>"]
                  <dataset>/<query>.<variant> ...
  --setup runs before the queries of the selectivity datasets (the "query" settings of the benchmark).
table: the builtin times of a run_bench.py run with the labels a1 and b (1 thread) - b/a1 per query and per dataset.
  perf_compare.py table <result folder>
"""
import csv
import glob
import math
import os
import subprocess
import sys
import tempfile

DATA_DIRS = {"tpch_sf1": "nested-parquet-datasets/nested-tpch", "tpch_sf10": "nested-parquet-datasets/nested-tpch-sf10",
             "xmark": "nested-parquet-datasets/xmark", "dblp": "nested-parquet-datasets/dblp",
             "selectivity_random": "selectivity_random", "selectivity_sorted": "selectivity_sorted"}


def geomean(values):
    return math.exp(sum(math.log(v) for v in values) / len(values)) if values else float("nan")


def perf_counts(binary, data_dir, sql_file, events):
    """The counts of the events of one process, or an error message"""
    with tempfile.NamedTemporaryFile(suffix=".csv") as out:
        proc = subprocess.run(["perf", "stat", "-x,", "-e", events, "-o", out.name, "--", binary, "-no-agent", "-f",
                               sql_file], cwd=data_dir, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        lines = open(out.name).read().splitlines()
    if proc.returncode != 0:
        return proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit status {proc.returncode}"
    counts = {}
    for line in lines:
        fields = line.split(",")
        if len(fields) < 3 or line.startswith("#"):
            continue
        if not fields[0].replace(".", "").isdigit():
            return f"{fields[2]}: {fields[0]}"
        # perf adds a modifier to the name (cycles -> cycles:u) depending on the permissions
        counts[fields[2].split(":")[0]] = float(fields[0])
    return counts


def perf_main(args):
    binaries, options, queries = [], {"repeat": "5", "runs-per-process": "3", "events": "instructions:u,cycles:u"}, []
    i = 0
    while i < len(args):
        if args[i] == "--binary":
            label, _, path = args[i + 1].partition("=")
            binaries.append((label, os.path.expanduser(path)))
            i += 2
        elif args[i].startswith("--"):
            options[args[i][2:]] = args[i + 1]
            i += 2
        else:
            queries.append(args[i])
            i += 1
    if len(binaries) != 2 or "queries" not in options or "data" not in options or not queries:
        sys.exit(__doc__)
    events = [event.split(":")[0] for event in options["events"].split(",")]
    first, second = binaries[0][0], binaries[1][0]
    print(f"Smallest of {options['repeat']} processes per binary, each running the query {options['runs-per-process']} "
          f"times with 1 thread. Ratios: {second} / {first}.\n")
    header = ["query"] + [f"{e} {label}" for e in events for label, _ in binaries] + [f"{e} {second}/{first}"
                                                                                      for e in events]
    if len(events) == 2:
        header += [f"IPC {first}", f"IPC {second}"]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for query in queries:
        dataset, name = query.split("/", 1)
        sql = open(os.path.join(os.path.expanduser(options["queries"]), dataset, name + ".sql")).read()
        sql = sql.strip().rstrip(";") + ";\n"
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as script:
            setup = options.get("setup", "") + "\n" if dataset.startswith("selectivity") else ""
            script.write("SET threads = 1;\n" + setup + ".mode trash\n" + sql * int(options["runs-per-process"]))
        data_dir = os.path.join(os.path.expanduser(options["data"]), DATA_DIRS[dataset])
        best = {label: {} for label, _ in binaries}
        error = None
        for _ in range(int(options["repeat"])):
            for label, path in binaries:
                counts = perf_counts(path, data_dir, script.name, options["events"])
                if isinstance(counts, str):
                    error = f"{label}: {counts}"
                    break
                for event in events:
                    if event in counts:
                        best[label][event] = min(best[label].get(event, counts[event]), counts[event])
            if error:
                break
        os.unlink(script.name)
        if error:
            print(f"| {query} | ERROR {error} |")
            continue
        row = [query]
        for event in events:
            row += [f"{best[label].get(event, float('nan')):.4g}" for label, _ in binaries]
        for event in events:
            a, b = best[first].get(event), best[second].get(event)
            row.append(f"{b / a:.4f}" if a and b else "-")
        if len(events) == 2:
            for label, _ in binaries:
                ins, cyc = best[label].get(events[0]), best[label].get(events[1])
                row.append(f"{ins / cyc:.3f}" if ins and cyc else "-")
        print("| " + " | ".join(row) + " |")


def table_main(folder):
    all_ratios = []
    print("| dataset | query | builtin a1 | builtin b | b/a1 | same result |")
    print("|---|---|---|---|---|---|")
    summary = []
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        dataset = os.path.basename(path)[:-4]
        ratios = []
        for row in csv.DictReader(line for line in open(path) if not line.startswith("#")):
            a, b = float(row["builtin_a1_s"]), float(row["builtin_b_s"])
            ratios.append(b / a)
            same = row["builtin_a1_result"] == row["builtin_b_result"]
            print(f"| {dataset} | {row['query']} | {a:.3f} | {b:.3f} | {b / a:.3f} | {'yes' if same else 'NO'} |")
        summary.append((dataset, geomean(ratios)))
        all_ratios += ratios
    print("\n| dataset | builtin b/a1 (geomean) |")
    print("|---|---|")
    for dataset, ratio in summary:
        print(f"| {dataset} | {ratio:.3f} |")
    print(f"| all queries | {geomean(all_ratios):.3f} |")
    print(f"\nb is faster than a1 in {sum(1 for r in all_ratios if r < 1)} of {len(all_ratios)} builtin queries.")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "perf":
        perf_main(sys.argv[2:])
    elif len(sys.argv) == 3 and sys.argv[1] == "table":
        table_main(sys.argv[2])
    else:
        sys.exit(__doc__)
