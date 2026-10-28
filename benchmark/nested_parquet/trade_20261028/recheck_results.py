#!/usr/bin/env python3
"""Summarize the recheck step of run_trade.sh: for every run_bench.py CSV under the folder (<layout>/<dataset>.csv),
the queries and their result checks (*_ok columns) - all columns of a result are compared since commit ff891acd2dd.

Usage: recheck_results.py <recheck folder>
"""
import csv
import os
import sys


def reference(row, key):
    """What the column was compared with: <variant>_reference of the longest variant that prefixes the column."""
    suffix = "_reference"
    variants = [k[: -len(suffix)] for k in row if k.endswith(suffix) and key.startswith(k[: -len(suffix)])]
    return row[max(variants, key=len) + "_reference"] if variants else ""


root = sys.argv[1]
total = failed = 0
print("| layout | dataset | queries | checks | failed |")
print("|---|---|---|---|---|")
failures = []
for layout in sorted(os.listdir(root)):
    folder = os.path.join(root, layout)
    if not os.path.isdir(folder):
        continue
    for name in sorted(f for f in os.listdir(folder) if f.endswith(".csv")):
        rows = list(csv.DictReader(open(os.path.join(folder, name))))
        checks = [
            (row["query"], key, row[key], reference(row, key)) for row in rows for key in row if key.endswith("_ok")
        ]
        bad = [c for c in checks if c[2] != "True"]
        total += len(checks)
        failed += len(bad)
        failures += [(layout, name[:-4]) + c for c in bad]
        print(f"| {layout} | {name[:-4]} | {len(rows)} | {len(checks)} | {len(bad)} |")
print(f"\n{total} checks, {failed} failed")
for layout, dataset, query, key, value, compared_with in failures:
    print(f"- {layout} {dataset} {query}: {key} = {value} (reference: {compared_with})")
