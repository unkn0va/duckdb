#!/usr/bin/env python3
"""Summarize the CSVs of run_all.sh as Markdown tables: how many times faster the flat query of main_rey is than the
builtin query of the original DuckDB ("builtin / flat" = builtin seconds / flat seconds; > 1: flat is faster), per
dataset and thread count, and per query. XMark uses the flat_minmax form. With split results, "split / flat" as well.

Times are the fastest of the runs (run_bench.py). A result that differs from its reference is marked with (!).

Usage: summarize.py <results folder> [--base-label base] [--final-label final]
"""
import csv
import glob
import math
import os
import re
import sys

DATASETS = ["tpch_sf1", "tpch_sf10", "xmark", "dblp", "selectivity_random", "selectivity_sorted"]
NAMES = {"tpch_sf1": "TPC-H SF1", "tpch_sf10": "TPC-H SF10", "xmark": "XMark", "dblp": "DBLP",
         "selectivity_random": "Selectivity (A), a % N = 0", "selectivity_sorted": "Selectivity (B), a < 10^6 / N"}
FLAT_VARIANTS = ("flat", "flat_minmax")


def option(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def number(row, key):
    value = row.get(key)
    return float(value) if value else None


def geometric_mean(values):
    values = [v for v in values if v]
    return math.exp(sum(math.log(v) for v in values) / len(values)) if values else None


def query_name(dataset, query):
    if dataset.startswith("selectivity") and re.fullmatch(r"n\d", query):
        return "N = 1" if query == "n0" else f"N = 10^{query[1:]}"
    return query


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print(__doc__)
        return 2
    folder, base, final = sys.argv[1], option("--base-label", "base"), option("--final-label", "final")
    tables = {}
    for dataset in DATASETS + sorted(set(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(folder, "*.csv")))
                                     - set(DATASETS)):
        path = os.path.join(folder, f"{dataset}.csv")
        if not os.path.exists(path) or dataset in tables:
            continue
        with open(path) as f:
            rows = list(csv.DictReader(f))
        threads = sorted({int(m.group(1)) for row in rows for key in row
                          for m in [re.fullmatch(rf"builtin_{base}_t(\d+)_s", key)] if m})
        tables[dataset] = (rows, threads)

    all_threads = sorted({t for _, threads in tables.values() for t in threads})
    print("# Nested Parquet benchmark: builtin / flat\n")
    print(f"builtin = the original DuckDB (`{base}`), flat = `read_parquet_flat` of main_rey (`{final}`; XMark: the "
          "flat_minmax form). Ratio = builtin seconds / flat seconds (> 1: flat is faster); fastest of the runs.\n")
    print("## Per dataset and thread count (geometric mean over the queries)\n")
    print("| dataset | " + " | ".join(f"threads={t}" for t in all_threads) + " |")
    print("|---|" + "---|" * len(all_threads))
    per_query = {}
    for dataset, (rows, threads) in tables.items():
        cells, per_query[dataset] = [], []
        for t in all_threads:
            ratios = []
            for row in rows:
                variant = next((v for v in FLAT_VARIANTS if row.get(f"{v}_{final}_t{t}_s")), None)
                builtin = number(row, f"builtin_{base}_t{t}_s")
                flat = number(row, f"{variant}_{final}_t{t}_s") if variant else None
                split = number(row, f"split_{final}_t{t}_s")
                ok = row.get(f"{variant}_{final}_ok", "") if variant else ""
                ratios.append(builtin / flat if builtin and flat else None)
                per_query[dataset].append((row["query"], t, variant, builtin, flat, split, ok,
                                           row.get(f"split_{final}_ok", "")))
            mean = geometric_mean(ratios)
            cells.append(f"{mean:.2f}x" if mean else "-")
        print(f"| {NAMES.get(dataset, dataset)} | " + " | ".join(cells) + " |")

    print("\n## Per query\n")
    print("Seconds: builtin / flat = ratio" + ("; split / flat = ratio" if any(
        q[5] for qs in per_query.values() for q in qs) else "") + ".\n")
    for dataset, (rows, threads) in tables.items():
        has_split = any(q[5] for q in per_query[dataset])
        print(f"### {NAMES.get(dataset, dataset)}\n")
        print("| query | " + " | ".join(f"threads={t}" for t in threads) + " |")
        print("|---|" + "---|" * len(threads))
        for row in rows:
            cells = []
            for t in threads:
                entry = next(q for q in per_query[dataset] if q[0] == row["query"] and q[1] == t)
                _, _, variant, builtin, flat, split, ok, split_ok = entry
                mark = "" if ok == "True" else " (!)"
                cell = (f"{builtin:.3f} / {flat:.3f} = **{builtin / flat:.2f}x**{mark}" if builtin and flat
                        else f"{builtin or '-'} / {flat or '-'}{mark}")
                if has_split and split and flat:
                    cell += f"; split {split:.3f} = {split / flat:.2f}x" + ("" if split_ok == "True" else " (!)")
                cells.append(cell)
            name = query_name(dataset, row["query"])
            variant = next((q[2] for q in per_query[dataset] if q[0] == row["query"] and q[2]), "flat")
            print(f"| {name}{' (' + variant + ')' if variant != 'flat' else ''} | " + " | ".join(cells) + " |")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
