#!/usr/bin/env python3
"""Estimated vs actual rows of every join, UNNEST and their input scans (issue 2-2).

Every <name>.<variant>.sql of the query directory runs once with EXPLAIN (ANALYZE, FORMAT json) in the configurations
of its variant: builtin -> base, prenestoff, prenest (method A, nested); flat, flat_minmax, flat_umbra -> flat (main_rey)
and split -> pure flat (base) (method B). One CSV row per operator of interest:
  - joins (HASH_JOIN, ..., CROSS_PRODUCT) and UNNEST, with their kind:
      nesting: parent-child   a join on node keys: _sk / sk of one side = _akN / akN of the other (flat, pure flat)
      nesting: sibling        both sides _akN / akN, or the row numbers of two unnested lists (q4_two builtin: rn)
      nesting: same node      both sides _sk / sk
      nesting: UNNEST         method A's counterpart of the parent-child join. UNNEST has no estimate of its own: the
                              logical operator takes the largest estimate of its children
                              (src/planner/logical_operator.cpp:261-272), so est = the estimate of its input
      regular                 every other join (the dimension tables, ...)
  - the TABLE_SCANs below them, with the join they feed (feeds, side): their actual rows are after the filters and
    after the dynamic join filters (column dynamic_filters) - the estimate does not know the latter
q_error = max(est / actual, actual / est), both clamped to at least 1.
For a scan of read_parquet_flat (File + Node) the parquet metadata of the node's own leaves is added: nv_first =
sum of num_values of its first leaf in schema order, nv_leaves = the distinct sums of all its leaves, and
nv_relation = how the estimate relates to them (est = nv_first, est = nv_first x f for a filter, ...), and
node_rows = the rows of the node (count over read_parquet_node, without the placeholders of empty or NULL lists that
num_values counts) - the actual rows of the scan itself can be fewer than that even without a filter, when
read_parquet_flat skips the tasks of rows a join cannot match.

Usage: [THREADS=20] [VARIANTS="builtin flat split"] [FLAT_SETUP=sql] [QUERIES="q1 q2"]
       cardinality.py <dataset label> <query dir> <data dir> <out csv>
The CSV is appended to (header when it is new). Environment: BASE, PRENEST, FINAL as in time_queries.py.
"""
import csv
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plans import describe, explain_analyze, operators  # noqa: E402

NB = os.path.expanduser("~/nested-bench")
BASE = os.environ.get("BASE", f"{NB}/duckdb_base/build/release/duckdb")
PRENEST = os.environ.get("PRENEST", f"{NB}/duckdb_prenest_base/build/release/duckdb")
FINAL = os.environ.get("FINAL", f"{NB}/duckdb_rey/build/release/duckdb")
THREADS = os.environ.get("THREADS", "20")
FLAT_SETUP = os.environ.get("FLAT_SETUP", "")
CONFIGS = {  # variant: [(config, method, binary, setup)]
    "builtin": [
        ("base", "A", BASE, ""),
        ("prenestoff", "A", PRENEST, "SET parquet_prenest_auto = false;"),
        ("prenest", "A", PRENEST, "SET parquet_prenest_auto = true;"),
    ],
    "flat": [("flat", "B", FINAL, FLAT_SETUP)],
    "flat_minmax": [("flat", "B", FINAL, FLAT_SETUP)],
    "flat_umbra": [("flat", "B", FINAL, FLAT_SETUP)],
    "split": [("pureflat", "B", BASE, "")],
}
FIELDS = [
    "dataset", "query", "variant", "config", "method", "op_id", "op", "kind", "feeds", "side", "detail",
    "est", "actual", "q_error", "dynamic_filters", "filters", "nv_first", "nv_leaves", "nv_relation", "node_rows", "error",
]
KEY = re.compile(r"^(_?sk|_?ak\d+|rn|file_row_number)$")
WRAPPERS = {"list", "element", "array", "item", "bag", "key_value"}


def q_error(est, actual):
    if est is None or actual is None:
        return ""
    est, actual = max(est, 1), max(actual, 1)
    return f"{max(est / actual, actual / est):.3f}"


def condition_columns(conditions):
    """[(left column, right column)] of a join's conditions, column names without table, path and casts."""
    if isinstance(conditions, str):
        conditions = re.split(r"\s+AND\s+", conditions)
    pairs = []
    for condition in conditions or []:
        sides = re.split(r"\s*(?:=|<>|!=|<=|>=|<|>|IS NOT DISTINCT FROM)\s*", condition, maxsplit=1)
        names = []
        for side in sides:
            identifiers = re.findall(r'"([^"]+)"|([A-Za-z_][A-Za-z_0-9.]*)', side)
            words = [a or b for a, b in identifiers if (a or b).upper() not in ("CAST", "AS", "INTEGER", "BIGINT")]
            names.append(words[-1].split(".")[-1] if words else "")
        if len(names) == 2:
            pairs.append(tuple(names))
    return pairs


def join_kind(op):
    if op["type"] == "UNNEST":
        return "nesting: UNNEST"
    pairs = condition_columns(op["extra"].get("Conditions"))
    if not pairs or not all(KEY.match(a) and KEY.match(b) for a, b in pairs):
        return "regular"
    kinds = set()
    for a, b in pairs:
        roles = {"sk" if re.match(r"^_?sk$", c) else "ak" for c in (a, b)}
        kinds.add("parent-child" if roles == {"sk", "ak"} else "same node" if roles == {"sk"} else "sibling")
    return "nesting: " + "/".join(sorted(kinds))


class Metadata:
    """num_values per leaf of the parquet files, by node path."""

    def __init__(self, data_dir):
        self.data_dir, self.files, self.rows = data_dir, {}, {}

    def leaves(self, file):
        if file not in self.files:
            sql = (
                "SELECT path_in_schema, min(column_id), sum(num_values) FROM parquet_metadata('" + file.replace("'", "''")
                + "') GROUP BY path_in_schema ORDER BY 2"
            )
            run = subprocess.run(
                [BASE, "-no-agent", "-csv", "-noheader", "-c", sql], capture_output=True, text=True, cwd=self.data_dir
            )
            leaves = []
            for line in run.stdout.splitlines():
                path, _, nv = line.rsplit(",", 2)
                parts = [p.strip() for p in path.strip('"').split(",")]
                leaves.append(([p for p in parts if p not in WRAPPERS], int(nv)))
            self.files[file] = leaves
        return self.files[file]

    def node_rows(self, file, node):
        """The rows of a node of read_parquet_flat, without the placeholders of empty and NULL lists."""
        key = (file, node)
        if key not in self.rows:
            sql = (f"SET threads = {THREADS}; SELECT count(_sk) FROM read_parquet_node('" + file.replace("'", "''")
                   + "', node := '" + node.replace("'", "''") + "')")
            run = subprocess.run([FINAL, "-no-agent", "-csv", "-noheader", "-c", sql], capture_output=True, text=True,
                                 cwd=self.data_dir)
            self.rows[key] = run.stdout.strip() if run.returncode == 0 else ""
        return self.rows[key]

    def node(self, file, node):
        """num_values of the leaves directly in a node, in schema order."""
        prefix = [] if node in ("", "(top level)") else node.split(".")
        return [nv for path, nv in self.leaves(file) if path[:-1] == prefix]


def relation(est, nv_first, has_filter):
    if est is None or not nv_first:
        return ""
    if est == nv_first:
        return "est = nv_first"
    ratio = est / nv_first
    return f"est = nv_first x {ratio:.3g}" + (" (filter)" if has_filter else "")


def rows_of(dataset, name, variant, config, method, profile, metadata):
    ops = operators(profile)
    by_id = {op["id"]: op for op in ops}
    interesting = {op["id"] for op in ops if "JOIN" in op["type"] or op["type"] in ("CROSS_PRODUCT", "UNNEST")}
    rows = []
    for op in ops:
        if op["id"] not in interesting and op["type"] != "TABLE_SCAN":
            continue
        # the join or UNNEST this operator feeds, and on which side
        feeds, side, cur = "", "", op
        while cur["parent"] is not None:
            parent = by_id[cur["parent"]]
            if parent["id"] in interesting:
                feeds, side = parent["id"], cur["role"] or "input"
                break
            cur = parent
        if op["type"] == "TABLE_SCAN" and feeds == "":
            continue
        est = op["est"]
        if op["type"] == "UNNEST" and est is None:
            child = next((c for c in ops if c["parent"] == op["id"]), None)
            est = child["est"] if child else None
        extra = op["extra"]
        row = {
            "dataset": dataset, "query": name, "variant": variant, "config": config, "method": method,
            "op_id": op["id"], "op": op["type"], "feeds": feeds, "side": side, "detail": describe(extra)[:200],
            "est": "" if est is None else est, "actual": op["actual"], "q_error": q_error(est, op["actual"]),
            "dynamic_filters": "yes" if extra.get("Dynamic Filters") else "",
            "filters": "yes" if extra.get("Filters") else "",
            "kind": join_kind(op) if op["id"] in interesting else "scan",
        }
        if op["type"] == "TABLE_SCAN" and extra.get("File") and "Node" in extra:
            leaves = metadata.node(extra["File"], extra["Node"])
            if leaves:
                row["nv_first"] = leaves[0]
                row["nv_leaves"] = "/".join(str(v) for v in sorted(set(leaves)))
                row["nv_relation"] = relation(est, leaves[0], bool(extra.get("Filters")))
                if extra["Node"] not in ("", "(top level)"):
                    row["node_rows"] = metadata.node_rows(extra["File"], extra["Node"])
        rows.append(row)
    return rows


def main():
    dataset, query_dir, data_dir, out_csv = sys.argv[1:5]
    data_dir = os.path.abspath(data_dir)
    variants = os.environ.get("VARIANTS", "builtin flat split").split()
    only = os.environ.get("QUERIES", "").split()
    metadata = Metadata(data_dir)
    new = not os.path.exists(out_csv)
    with open(out_csv, "a", newline="") as f:
        writer = csv.DictWriter(f, FIELDS)
        if new:
            writer.writeheader()
        for file in sorted(os.listdir(query_dir)):
            m = re.match(r"(.+)\.([a-z_]+)\.sql$", file)
            if not m or m.group(2) not in variants or (only and m.group(1) not in only):
                continue
            name, variant = m.groups()
            query = open(os.path.join(query_dir, file)).read()
            for config, method, binary, setup in CONFIGS[variant]:
                try:
                    profile = explain_analyze(binary, data_dir, setup, query, THREADS)
                    rows = rows_of(dataset, name, variant, config, method, profile, metadata)
                except (RuntimeError, subprocess.TimeoutExpired) as e:
                    rows = [{"dataset": dataset, "query": name, "variant": variant, "config": config, "method": method,
                             "error": str(e)[:200]}]
                writer.writerows(rows)
                f.flush()
                joins = sum(1 for r in rows if r.get("kind", "scan") not in ("scan", ""))
                print(f"{dataset:18} {name:16} {config:10} {joins} joins/unnests"
                      + (f"  ERROR {rows[0]['error']}" if rows and rows[0].get("error") else ""), flush=True)


if __name__ == "__main__":
    main()
