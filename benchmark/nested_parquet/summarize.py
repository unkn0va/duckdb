#!/usr/bin/env python3
"""Summarize the CSVs of run_all.sh as Markdown tables: how many times faster the flat query of main_rey is than the
builtin query of the original DuckDB ("builtin / flat" = builtin seconds / flat seconds; > 1: flat is faster), per
dataset and thread count, and per query. XMark uses the flat_minmax form. With split results, "split / flat" as well.

Times are the fastest of the runs (run_bench.py). A query is left out of a geometric mean, marked with (!) and listed
with the reason when its result check failed, or when its flat result differs from the builtin result (a variant that
passed only against its .oracle computes something else than the builtin query).

When the builtin queries also ran with prenest-3way (run_all.sh --prenest, labels prenest and prenestoff), a further
section puts the three binaries side by side.

Usage: summarize.py <results folder> [--base-label base] [--final-label final]
"""
import csv
import glob
import math
import os
import re
import sys

DATASETS = ["tpch_sf1", "tpch_sf10", "xmark", "dblp", "selectivity_random", "selectivity_sorted"]
NAMES = {
    "tpch_sf1": "TPC-H SF1",
    "tpch_sf10": "TPC-H SF10",
    "xmark": "XMark",
    "dblp": "DBLP",
    "selectivity_random": "Selectivity (A), a % N = 0",
    "selectivity_sorted": "Selectivity (B), a < 10^6 / N",
}
FLAT_VARIANTS = ("flat", "flat_minmax")
PRENEST_LABELS = ("prenest", "prenestoff")


def option(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def number(row, key):
    value = row.get(key)
    return float(value) if value else None


def geometric_mean(values):
    values = [v for v in values if v]
    return math.exp(sum(math.log(v) for v in values) / len(values)) if values else None


def flat_problem(row, base, final):
    """Why the builtin / flat ratio of a query does not compare the same work, or None."""
    variant = next((v for v in FLAT_VARIANTS if row.get(f"{v}_{final}_result")), None)
    if variant is None:
        return None
    if row.get(f"{variant}_{final}_ok") != "True":
        return f"{variant}: the result check failed"
    same = row.get(f"{variant}_{final}_same")  # CSVs before the comparison with a tolerance: compare the hashes
    if (same == "False") if same else row[f"{variant}_{final}_result"] != row.get(f"builtin_{base}_result"):
        return f"{variant}: the result differs from the builtin query (it passed only against its oracle)"
    return None


def builtin_problem(row, base, label):
    """Why the builtin query of another binary (label) is not comparable with the one of base, or None."""
    if row.get(f"builtin_{label}_result") is not None and row.get(f"builtin_{label}_ok") != "True":
        return f"builtin of {label}: the result differs from the builtin query of {base}"
    return None


def print_excluded(excluded):
    if not excluded:
        return
    print("\nLeft out of the geometric means above (all thread counts):\n")
    for dataset, query, reason in excluded:
        print(f"- {NAMES.get(dataset, dataset)} - {query_name(dataset, query)} (`{query}`): {reason}")


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
    for dataset in DATASETS + sorted(
        set(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(folder, "*.csv"))) - set(DATASETS)
    ):
        path = os.path.join(folder, f"{dataset}.csv")
        if not os.path.exists(path) or dataset in tables:
            continue
        with open(path) as f:
            rows = list(csv.DictReader(f))
        threads = sorted(
            {
                int(m.group(1))
                for row in rows
                for key in row
                for m in [re.fullmatch(rf"builtin_{base}_t(\d+)_s", key)]
                if m
            }
        )
        tables[dataset] = (rows, threads)

    all_threads = sorted({t for _, threads in tables.values() for t in threads})
    print("# Nested Parquet benchmark: builtin / flat\n")
    print(
        f"builtin = the original DuckDB (`{base}`), flat = `read_parquet_flat` of main_rey (`{final}`; XMark: the "
        "flat_minmax form). Ratio = builtin seconds / flat seconds (> 1: flat is faster); fastest of the runs.\n"
    )
    print("## Per dataset and thread count (geometric mean over the queries)\n")
    print("| dataset | " + " | ".join(f"threads={t}" for t in all_threads) + " |")
    print("|---|" + "---|" * len(all_threads))
    per_query, excluded = {}, []
    for dataset, (rows, threads) in tables.items():
        cells, per_query[dataset] = [], []
        problems = {row["query"]: flat_problem(row, base, final) for row in rows}
        excluded += [(dataset, query, reason) for query, reason in problems.items() if reason]
        for t in all_threads:
            ratios = []
            for row in rows:
                variant = next((v for v in FLAT_VARIANTS if row.get(f"{v}_{final}_t{t}_s")), None)
                builtin = number(row, f"builtin_{base}_t{t}_s")
                flat = number(row, f"{variant}_{final}_t{t}_s") if variant else None
                split = number(row, f"split_{final}_t{t}_s")
                ok = "False" if problems[row["query"]] else row.get(f"{variant}_{final}_ok", "") if variant else ""
                ratios.append(builtin / flat if builtin and flat and not problems[row["query"]] else None)
                per_query[dataset].append(
                    (row["query"], t, variant, builtin, flat, split, ok, row.get(f"split_{final}_ok", ""))
                )
            mean = geometric_mean(ratios)
            cells.append(f"{mean:.2f}x" if mean else "-")
        print(f"| {NAMES.get(dataset, dataset)} | " + " | ".join(cells) + " |")
    print_excluded(excluded)

    print("\n## Per query\n")
    print(
        "Seconds: builtin / flat = ratio"
        + ("; split / flat = ratio" if any(q[5] for qs in per_query.values() for q in qs) else "")
        + ".\n"
    )
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
                cell = (
                    f"{builtin:.3f} / {flat:.3f} = **{builtin / flat:.2f}x**{mark}"
                    if builtin and flat
                    else f"{builtin or '-'} / {flat or '-'}{mark}"
                )
                if has_split and split and flat:
                    cell += f"; split {split:.3f} = {split / flat:.2f}x" + ("" if split_ok == "True" else " (!)")
                cells.append(cell)
            name = query_name(dataset, row["query"])
            variant = next((q[2] for q in per_query[dataset] if q[0] == row["query"] and q[2]), "flat")
            print(f"| {name}{' (' + variant + ')' if variant != 'flat' else ''} | " + " | ".join(cells) + " |")
        print()
    labels = [
        label
        for label in PRENEST_LABELS
        if any(row.get(f"builtin_{label}_t{t}_s") for rows, threads in tables.values() for row in rows for t in threads)
    ]
    if labels:
        print_prenest(tables, all_threads, base, final, labels)
    return 0


def print_prenest(tables, all_threads, base, final, labels):
    def seconds(row, t):
        # (seconds, why the column is not comparable with base or None) per column
        variant = next((v for v in FLAT_VARIANTS if row.get(f"{v}_{final}_t{t}_s")), None)
        flat = number(row, f"{variant}_{final}_t{t}_s") if variant else None
        values = [(number(row, f"builtin_{base}_t{t}_s"), None)]
        values += [(number(row, f"builtin_{label}_t{t}_s"), builtin_problem(row, base, label)) for label in labels]
        return values + [(flat, flat_problem(row, base, final))]

    names = [base] + list(labels) + [f"flat ({final})"]
    print("## Three binaries: original DuckDB, prenest-3way, main_rey\n")
    print(
        f"`{base}` = builtin query of the original DuckDB, `prenest` = the same builtin query with prenest-3way "
        "(parquet_prenest_auto = true)"
        + (
            ", `prenestoff` = prenest-3way with parquet_prenest_auto = false (still with its LIST<STRUCT> pruning)"
            if "prenestoff" in labels
            else ""
        )
        + f", flat = `read_parquet_flat` of main_rey (`{final}`). Ratio = {base} seconds / seconds of the column "
        "(> 1: faster than the original DuckDB); geometric mean over the queries, without those listed below the "
        "table.\n"
    )
    print("| dataset | threads | " + " | ".join(f"{base} / {name}" for name in names[1:]) + " |")
    print("|---|---|" + "---|" * (len(names) - 1))
    for dataset, (rows, threads) in tables.items():
        for t in threads:
            cells = []
            for i in range(1, len(names)):
                ratios = []
                for row in rows:
                    values = seconds(row, t)
                    comparable = values[0][0] and values[i][0] and not values[i][1]
                    ratios.append(values[0][0] / values[i][0] if comparable else None)
                mean = geometric_mean(ratios)
                cells.append(f"{mean:.2f}x" if mean else "-")
            print(f"| {NAMES.get(dataset, dataset)} | {t} | " + " | ".join(cells) + " |")
    print_excluded(
        [
            (dataset, row["query"], reason)
            for dataset, (rows, threads) in tables.items()
            for row in rows
            for reason in [builtin_problem(row, base, label) for label in labels] + [flat_problem(row, base, final)]
            if reason
        ]
    )
    print("\n### Per query (seconds)\n")
    print("| dataset | query | threads | " + " | ".join(names) + " |")
    print("|---|---|---|" + "---|" * len(names))
    for dataset, (rows, threads) in tables.items():
        for row in rows:
            for t in threads:
                cells = [
                    ("-" if value is None else f"{value:.3f}") + (" (!)" if problem and value is not None else "")
                    for value, problem in seconds(row, t)
                ]
                name = query_name(dataset, row["query"])
                print(f"| {NAMES.get(dataset, dataset)} | {name} | {t} | " + " | ".join(cells) + " |")
    print()


if __name__ == "__main__":
    sys.exit(main())
