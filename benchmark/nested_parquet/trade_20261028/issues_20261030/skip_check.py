#!/usr/bin/env python3
"""How many legs elements the condition of a query was evaluated on, and how many row groups the scan read
(follow-up G1: trade_B vs trade_Bsorted, whose row groups have narrow leg_id ranges that statistics can skip).

Per query file and configuration, from EXPLAIN (ANALYZE, FORMAT json) at 1 thread:
  base, prenestoff  the parquet scan's row_groups_scanned / total_row_groups_to_scan; elements evaluated = the rows
                    into the FILTER above UNNEST (every unnested element)
  prenest           the same counts; the reader evaluates every decoded element of the scanned row groups and the
                    upper FILTER again the kept ones - both are recorded
  flat              read_parquet_flat reports no row groups: the skipped tasks come from its debug log ("the filters
                    of the query skip X of Y tasks"), the evaluated elements from the parquet statistics - the
                    elements of the row groups whose smallest leg_id is below the query's constant (the others are
                    the ones a filter `leg_id < constant` can skip)
One CSV row per query and configuration.

Usage: [CONFIGS="base prenestoff prenest flat"] skip_check.py <query dir> <data dir> <out csv> <name> ...
Environment: BASE, PRENEST, FINAL as in time_queries.py
"""
import csv
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plans import explain_analyze, operators  # noqa: E402
from time_queries import ALL_CONFIGS, BASE, read_query  # noqa: E402

CONFIGS = os.environ.get("CONFIGS", "base prenestoff prenest flat").split()
FIELDS = ["name", "config", "file", "row_groups_scanned", "row_groups_total", "skipped_tasks", "elements_total",
          "elements_evaluated", "elements_evaluated_upper_filter", "elements_passing"]


def duckdb(binary, data_dir, sql):
    run = subprocess.run([binary, "-no-agent", "-csv", "-noheader"], input=sql, text=True, capture_output=True,
                         cwd=data_dir)
    return run.stdout


def row_group_elements(data_dir, file, constant):
    """(elements of the file, elements of the row groups whose smallest leg_id < constant, row groups, those)"""
    smallest = "coalesce(stats_min_value, stats_min)"  # pyarrow writes min_value, older writers min
    out = duckdb(BASE, data_dir, f"""SELECT sum(num_values), coalesce(sum(num_values) FILTER ({smallest} < '{constant}'), 0),
        count(*), count(*) FILTER ({smallest} < '{constant}') FROM parquet_metadata('{file}')
        WHERE path_in_schema = 'legs, list, element, leg_id';""")
    return [int(v) for v in out.strip().split(",")]


def main():
    query_dir, data_dir, out_csv, *names = sys.argv[1:]
    data_dir = os.path.abspath(data_dir)
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        for name in names:
            for config in CONFIGS:
                binary, config_setup, variant = ALL_CONFIGS[config]
                path = os.path.join(query_dir, f"{name}.{variant}.sql")
                if not os.path.exists(path):
                    continue
                file_setup, query = read_query(path)
                setup = config_setup + "\n" + file_setup
                file = re.search(r"'(trade_\w+\.parquet)'", query).group(1)
                constant = re.search(r"leg_id\"? < '(\w+)'", query).group(1)
                total, below, groups, groups_below = row_group_elements(data_dir, file, constant)
                ops = operators(explain_analyze(binary, data_dir, setup, query, 1))
                row = {"name": name, "config": config, "file": file, "elements_total": total}
                if variant == "flat":
                    log = duckdb(binary, data_dir, f"SET threads = 1;\n{setup}\nCALL enable_logging(level := 'debug', "
                                 f"storage := 'memory');\n.mode trash\n{query};\n.mode list\nSELECT message FROM duckdb_logs "
                                 "WHERE message LIKE 'read_parquet_node: the filters%';\n")
                    skips = re.findall(r'skip (\d+) of (\d+) tasks of node "legs"', log)
                    skipped = (f"{sum(int(a) for a, _ in skips)}/{sum(int(b) for _, b in skips)}" if skips
                               else "? (no log line)")
                    row.update(skipped_tasks=skipped,
                               row_groups_scanned=groups_below, row_groups_total=groups, elements_evaluated=below,
                               elements_passing=next(op["actual"] for op in ops if op["type"] == "TABLE_SCAN"
                                                     and op["extra"].get("Node") == "legs"))
                else:
                    scan = next(op for op in ops if op["type"] == "TABLE_SCAN")
                    unnest = next(op for op in ops if op["type"] == "UNNEST")
                    filt = next(op for op in ops if op["type"] == "FILTER")
                    row.update(row_groups_scanned=scan.get("row_groups_scanned", ""),
                               row_groups_total=scan.get("total_row_groups_to_scan", ""), skipped_tasks="",
                               elements_passing=filt["actual"])
                    if config == "prenest":
                        # the reader evaluates every element it decodes; the upper FILTER the ones it kept
                        row.update(elements_evaluated=total, elements_evaluated_upper_filter=unnest["actual"])
                    else:
                        row.update(elements_evaluated=unnest["actual"])
                writer.writerow(row)
                f.flush()
                print(name, config, {k: row.get(k) for k in FIELDS[3:]}, flush=True)


if __name__ == "__main__":
    main()
