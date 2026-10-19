#!/usr/bin/env python3
"""Table of the build experiment (SERVER.md, step 10): the flat queries with 1 thread in three binaries - a1 and a2
built from the same commit in two folders, b from another commit - and the builtin queries with the original DuckDB
(base), measured interleaved by run_bench.py. Per query: the seconds of each, a2/a1 (the difference between two builds
of the same code) and b/a1 (the difference between the commits); per dataset and over all queries their geometric
means. --earlier label=<result folder of run_all.sh> (repeatable) compares the builtin times with those of an earlier
run at 1 thread - when they match, the machine runs as fast as then.
Usage: build_diff_table.py <result folder> [--earlier label=<folder> ...]
"""
import csv
import glob
import math
import os
import sys


def load(path):
    return list(csv.DictReader(line for line in open(path) if not line.startswith("#")))


def geomean(values):
    return math.exp(sum(math.log(v) for v in values) / len(values)) if values else float("nan")


def main():
    folder = sys.argv[1]
    earlier = {}
    args = sys.argv[2:]
    while args:
        if args[0] != "--earlier" or len(args) < 2 or "=" not in args[1]:
            sys.exit(__doc__)
        label, _, path = args[1].partition("=")
        earlier[label] = path
        args = args[2:]
    all_a2, all_b = [], []
    summary = []
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        dataset = os.path.basename(path)[:-4]
        rows = load(path)
        variant = "flat_minmax" if dataset == "xmark" else "flat"
        print(f"## {dataset} ({variant})\n")
        print("| query | builtin base | a1 | a2 | b | a2/a1 | b/a1 | results |")
        print("|---|---|---|---|---|---|---|---|")
        a2_ratios, b_ratios = [], []
        for row in rows:
            seconds = {label: float(row[f"{variant}_{label}_s"]) for label in ("a1", "a2", "b")}
            ok = all(row.get(f"{variant}_{label}_ok") == "True" for label in ("a1", "a2", "b"))
            a2_ratios.append(seconds["a2"] / seconds["a1"])
            b_ratios.append(seconds["b"] / seconds["a1"])
            print(
                f"| {row['query']} | {float(row['builtin_base_s']):.3f} | {seconds['a1']:.3f} | {seconds['a2']:.3f} "
                f"| {seconds['b']:.3f} | {a2_ratios[-1]:.3f} | {b_ratios[-1]:.3f} | {'ok' if ok else 'DIFFERENT'} |"
            )
        all_a2 += a2_ratios
        all_b += b_ratios
        builtin = []
        for label, earlier_folder in earlier.items():
            earlier_path = os.path.join(earlier_folder, f"{dataset}.csv")
            if not os.path.exists(earlier_path):
                continue
            before = {row["query"]: row for row in load(earlier_path)}
            ratios = [
                float(row["builtin_base_s"]) / float(before[row["query"]]["builtin_base_t1_s"])
                for row in rows
                if row["query"] in before and before[row["query"]].get("builtin_base_t1_s")
            ]
            if ratios:
                builtin.append(f"{label} {geomean(ratios):.3f}")
        summary.append((dataset, geomean(a2_ratios), geomean(b_ratios), max(abs(r - 1) for r in a2_ratios), builtin))
        print()
    print("## Summary\n")
    print("| dataset | a2/a1 (geomean) | b/a1 (geomean) | largest a2/a1 difference | builtin now / earlier |")
    print("|---|---|---|---|---|")
    for dataset, a2, b, spread, builtin in summary:
        print(f"| {dataset} | {a2:.3f} | {b:.3f} | {spread * 100:.1f}% | {', '.join(builtin) or '-'} |")
    print(
        f"| all queries | {geomean(all_a2):.3f} | {geomean(all_b):.3f} | "
        f"{max(abs(r - 1) for r in all_a2) * 100:.1f}% | |"
    )
    faster = sum(1 for r in all_b if r < 1)
    print(
        f"\nb is faster than a1 in {faster} of {len(all_b)} queries; a2 is faster than a1 in "
        f"{sum(1 for r in all_a2 if r < 1)} of {len(all_a2)}."
    )


if __name__ == "__main__":
    main()
