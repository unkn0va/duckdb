#!/usr/bin/env python3
"""Check the results of a benchmark run: for every query, the result of every variant (flat, flat_minmax, split, ...)
must equal the builtin query's result - or the query's .oracle, where the variant's result differs from the builtin
one by definition (e.g. XMark Q2, whose flat join has no rows for the auctions without bidders). run_bench.py stores
the comparison per query in the <variant>_<label>_ok columns; this script collects them, and also reports queries that
failed or timed out.

Usage: check_results.py <results folder or CSV files...>
Exit status: 0 if all results match, 1 if any differs or failed.
"""
import csv
import glob
import os
import sys


def csv_files(args):
    for arg in args:
        if os.path.isdir(arg):
            yield from sorted(f for f in glob.glob(os.path.join(arg, "*.csv")))
        else:
            yield arg


def main():
    if not sys.argv[1:]:
        print(__doc__)
        return 2
    problems, checks = [], 0
    for path in csv_files(sys.argv[1:]):
        dataset = os.path.basename(path).removesuffix(".csv")
        with open(path) as f:
            rows = list(csv.DictReader(f))
        dataset_checks = 0
        for row in rows:
            for key, value in row.items():
                if key.endswith("_ok") and value:
                    checks += 1
                    dataset_checks += 1
                    if value != "True":
                        variant = key.removesuffix("_ok")
                        reference = row.get(variant.rsplit("_", 1)[0] + "_reference") or row.get(variant + "_reference")
                        problems.append(
                            f"{dataset} {row['query']}: {variant} differs from {reference or 'the reference'}"
                        )
                elif key.endswith("_error") and value:
                    problems.append(f"{dataset} {row['query']}: {key.removesuffix('_error')} failed: {value[:100]}")
        if dataset_checks == 0:
            problems.append(f"{dataset}: no result was compared (no variant besides builtin ran?)")
        print(f"{dataset}: {len(rows)} queries, {dataset_checks} comparisons")
    if problems:
        print("\n" + "!" * 78)
        print(f"!!! RESULT CHECK FAILED: {len(problems)} problem(s)")
        print("!" * 78)
        for problem in problems:
            print("  " + problem)
        print("The timings of these queries are not comparable. See SERVER.md, 'Common problems'.")
        return 1
    print(f"OK: all {checks} results equal the builtin results (or their oracles).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
