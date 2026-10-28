#!/usr/bin/env python3
"""Turn the CSV of run_bench.py into one row per query and thread count, with the columns of the "쿼리별 시간" sheet of
final_results.xlsx extended to the five configurations: the fastest time and the CPU time of each, and the ratios
base/prenestoff, prenestoff/prenest, base/prenest, base/flat, base/pure flat (> 1: the second is faster). "결과 일치" is
"yes" when every configuration's result equals base's builtin result.

Usage: summarize_trade.py <run_bench csv> <dataset name> <out csv>
"""
import csv
import os
import sys

source, dataset, out = sys.argv[1:4]
CONFIGS = [
    ("base", "builtin_base"),
    ("prenestoff", "builtin_prenestoff"),
    ("prenest", "builtin_prenest"),
    ("flat", "flat_final"),
    ("pure flat", "split_base"),
]
RATIOS = [
    ("base", "prenestoff"),
    ("prenestoff", "prenest"),
    ("base", "prenest"),
    ("base", "flat"),
    ("base", "pure flat"),
]

rows = list(csv.DictReader(open(source)))
# run_bench.py leaves the thread suffix out with a single thread count (THREADS gives it then)
threads = sorted(
    {key.rsplit("_t", 1)[1].split("_")[0] for key in rows[0] if "_t" in key and key.endswith("_s")}, key=int
)
threads = threads or [""]
header = (
    ["데이터셋", "쿼리", "스레드"]
    + [f"{label} (초)" for label, _ in CONFIGS]
    + [f"{label} CPU (초)" for label, _ in CONFIGS]
)
header += [f"{a} / {b}" for a, b in RATIOS] + ["결과 일치", "busy_cpu"]
with open(out, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(header)
    for row in rows:
        oks = [row[key] for key in row if key.endswith("_ok")]
        for t in threads:
            suffix = f"_t{t}" if t else ""
            seconds = {label: row.get(f"{prefix}{suffix}_s", "") for label, prefix in CONFIGS}
            cpu = [row.get(f"{prefix}{suffix}_cpu", "") for _, prefix in CONFIGS]
            ratios = [
                (
                    f"{float(seconds[a]) / float(seconds[b]):.3f}"
                    if seconds[a] and seconds[b] and float(seconds[b])
                    else ""
                )
                for a, b in RATIOS
            ]
            writer.writerow(
                [dataset, row["query"], t or os.environ.get("THREADS", "")]
                + [seconds[label] for label, _ in CONFIGS]
                + cpu
                + ratios
                + ["yes" if all(ok == "True" for ok in oks) else "NO", row.get("busy_cpu", "")]
            )
print(f"{out}: {len(rows)} queries x {len(threads)} thread counts")
