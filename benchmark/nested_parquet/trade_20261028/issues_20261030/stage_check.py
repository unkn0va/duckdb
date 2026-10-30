#!/usr/bin/env python3
"""Check that every stage query of queries_stage/ stops where it should (issue 1-1), from its physical plan
(EXPLAIN (FORMAT json)): the operators, the columns the scans read and their filters, in every configuration.
  s1_box      a scan of legs (or of its keys), no UNNEST, no FILTER
  s2_unnest   nested: UNNEST, no FILTER; flat, pure flat: the scan of leg_id and value, no FILTER, no join
  s2f_fields  as s2_unnest; nested scans read legs.leg_id and legs.value where struct fields are pruned
  s3_cond     nested: UNNEST and FILTER (prenest: also in the reader); flat, pure flat: a scan filter on leg_id
Prints a markdown table; the check column is "ok" or what is missing.

Usage: stage_check.py <query dir> <data dir>
Environment: BASE, PRENEST, FINAL as in time_queries.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from time_queries import ALL_CONFIGS, read_query  # noqa: E402

STAGES = ["s1_box", "s2_unnest", "s2f_fields", "s3_cond"]


def plan(binary, data_dir, setup, query):
    script = f"SET threads = 1;\n{setup}\nEXPLAIN (FORMAT json) {query};\n"
    out = subprocess.run([binary, "-no-agent", "-list", "-noheader"], input=script, text=True, capture_output=True,
                         cwd=data_dir).stdout
    return json.loads(out[out.index("[") : out.rindex("]") + 1])


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node.get("children", []))


def as_text(value):
    return ", ".join(value) if isinstance(value, list) else str(value or "")


def check(stage, nested, ops, scans):
    names = [n["name"] for n in ops]
    reads = " ".join(as_text(s.get("extra_info", {}).get("Projections")) for s in scans)
    filters = " ".join(as_text(s.get("extra_info", {}).get("Filters")) for s in scans)
    problems = []
    if not scans or not reads.strip():
        problems.append("no scan reads a column")
    if stage == "s1_box":
        problems += [f"has {op}" for op in ("UNNEST", "FILTER") if op in names]
    elif stage in ("s2_unnest", "s2f_fields"):
        if nested and "UNNEST" not in names:
            problems.append("no UNNEST")
        if "FILTER" in names or filters:
            problems.append("has a filter")
        if not nested and not ("leg_id" in reads and "value" in reads):
            problems.append("does not read leg_id and value")
    else:
        if nested and not ("UNNEST" in names and "FILTER" in names):
            problems.append("no UNNEST + FILTER")
        if not nested and "leg_id" not in filters:
            problems.append("no scan filter on leg_id")
    if any("JOIN" in n for n in names):
        problems.append("has a join")
    return "ok" if not problems else "; ".join(problems)


def main():
    query_dir, data_dir = sys.argv[1], os.path.abspath(sys.argv[2])
    print("| stage | config | operators (root → scan) | scan reads | scan filters | check |")
    print("|---|---|---|---|---|---|")
    for stage in STAGES:
        for config, (binary, config_setup, variant) in ALL_CONFIGS.items():
            file_setup, query = read_query(os.path.join(query_dir, f"{stage}.{variant}.sql"))
            ops = list(flatten(plan(binary, data_dir, config_setup + "\n" + file_setup, query)))
            scans = [n for n in ops if not n.get("children")]
            reads = "; ".join(
                (f"{s['extra_info']['Node']}: " if s.get("extra_info", {}).get("Node") else "")
                + as_text(s.get("extra_info", {}).get("Projections"))
                for s in scans
            )
            filters = "; ".join(as_text(s.get("extra_info", {}).get("Filters")) for s in scans if s.get("extra_info", {}).get("Filters"))
            chain = " → ".join(n["name"] for n in ops)
            print(f"| {stage} | {config} | {chain} | {reads} | {filters} | {check(stage, variant == 'builtin', ops, scans)} |")


if __name__ == "__main__":
    main()
