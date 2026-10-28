#!/usr/bin/env python3
"""Check the trade queries before measuring them, one line per query (README.md, "2-2"):
  - the results of the five configurations agree, in every data folder given: base / prenestoff / prenest run the
    builtin query, flat (main_rey) the flat one, pure flat (base) the split one; compared with base's builtin result
    after rounding numbers to 12 significant digits, rows sorted
  - prenest: whether it fired - the reader counters of parquet_prenest_stat after the query (reset before),
    parquet_prenest_lists() and the optimizer's opt:specs_pushed - in the first data folder; predicate_elements counts
    the evaluations of the condition including the re-evaluation of carried-over elements, so it can exceed
    elements_decoded
  - the joins in the physical plans (EXPLAIN (FORMAT json)) of the builtin, flat and pure flat queries

Usage: check_queries.py <query dir> <data dir> [<data dir> ...]
Environment: BASE, PRENEST, FINAL (binaries, default ~/nested-bench/...), QUERIES="q1_s01 q2_s50" (a subset)
"""
import json
import os
import subprocess
import sys

NB = os.path.expanduser("~/nested-bench")
BASE = os.environ.get("BASE", f"{NB}/duckdb_base/build/release/duckdb")
PRENEST = os.environ.get("PRENEST", f"{NB}/duckdb_prenest_base/build/release/duckdb")
FINAL = os.environ.get("FINAL", f"{NB}/duckdb_rey/build/release/duckdb")
CONFIGS = [  # label, binary, setup, variant
    ("base", BASE, "", "builtin"),
    ("prenestoff", PRENEST, "SET parquet_prenest_auto = false;", "builtin"),
    ("prenest", PRENEST, "SET parquet_prenest_auto = true;", "builtin"),
    ("flat", FINAL, "", "flat"),
    ("pure flat", BASE, "", "split"),
]
STATS = ["predicate_elements", "elements_decoded", "elements_appended"]


def duckdb(binary, sql, cwd, mode="-csv"):
    run = subprocess.run([binary, "-no-agent", mode, "-noheader", "-c", sql], capture_output=True, text=True, cwd=cwd)
    if run.returncode or run.stderr.strip():
        return None, (run.stderr.strip() or f"exit {run.returncode}").splitlines()[0][:160]
    return run.stdout, ""


def normalize(output):
    def value(text):
        try:
            return f"{float(text):.12g}"
        except ValueError:
            return text

    return sorted(tuple(value(v) for v in line.split(",")) for line in output.splitlines() if line)


def joins(binary, sql, cwd):
    out, error = duckdb(binary, f"SET threads = 1; EXPLAIN (FORMAT json) {sql.rstrip().rstrip(';')}", cwd, "-list")
    if out is None:
        return f"error: {error}"
    start = out.index("[")
    plan = json.loads(out[start : out.rindex("]") + 1])
    names = []

    def walk(node):
        if "JOIN" in node["name"] or node["name"] in ("CROSS_PRODUCT", "POSITIONAL_SCAN"):
            names.append(node["name"])
        for child in node.get("children", []):
            walk(child)

    for node in plan:
        walk(node)
    return f"{len(names)}" + (f" ({', '.join(sorted(set(names)))})" if names else "")


def main():
    query_dir, data_dirs = sys.argv[1], sys.argv[2:]
    names = sorted({f.split(".")[0] for f in os.listdir(query_dir) if f.endswith(".sql")})
    if os.environ.get("QUERIES"):
        names = [n for n in names if n in os.environ["QUERIES"].split()]
    read = lambda name, variant: open(os.path.join(query_dir, f"{name}.{variant}.sql")).read()

    header = ["query"] + [f"same: {os.path.basename(d.rstrip('/'))}" for d in data_dirs]
    header += ["prenest lists", "specs_pushed"] + STATS + ["evaluated / decoded", "appended / decoded"]
    header += ["joins builtin", "joins flat", "joins pure flat"]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for name in names:
        row = [name]
        for data in data_dirs:
            results = {}
            for label, binary, setup, variant in CONFIGS:
                out, error = duckdb(binary, setup + read(name, variant), data)
                results[label] = normalize(out) if out is not None else f"error: {error}"
            differ = [label for label in results if results[label] != results["base"]]
            errors = [f"{label}: {results[label]}" for label in results if isinstance(results[label], str)]
            row.append("yes" if not differ else "**no** " + "; ".join(errors or [f"differ: {', '.join(differ)}"]))
        probe = (
            ";".join(
                [
                    "SET parquet_prenest_auto = true",
                    "SELECT parquet_prenest_stat('reset')",
                    read(name, "builtin").rstrip(";\n"),
                    "SELECT parquet_prenest_lists()",
                    "SELECT parquet_prenest_stat('opt:specs_pushed')",
                ]
                + [f"SELECT parquet_prenest_stat('{s}')" for s in STATS]
            )
            + ";"
        )
        out, error = duckdb(PRENEST, probe, data_dirs[0])
        if out is None:
            row += [f"error: {error}"] + [""] * (3 + len(STATS))
        else:
            values = out.splitlines()[-(2 + len(STATS)) :]
            evaluated, decoded, appended = (int(v) for v in values[2:])
            ratios = [f"{evaluated / decoded:.3f}", f"{appended / decoded:.3f}"] if decoded else ["-", "-"]
            row += [values[0].strip('"') or "-"] + values[1:] + ratios
        row += [
            joins(BASE, read(name, "builtin"), data_dirs[0]),
            joins(FINAL, read(name, "flat"), data_dirs[0]),
            joins(BASE, read(name, "split"), data_dirs[0]),
        ]
        print("| " + " | ".join(row) + " |", flush=True)


if __name__ == "__main__":
    main()
