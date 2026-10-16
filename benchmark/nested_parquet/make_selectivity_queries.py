#!/usr/bin/env python3
"""Write the queries of the selectivity benchmark (the counterpart of the paper's Fig. 15) into queries/:

- selectivity_random: the paper's synthetic/l1.parquet ("a" random) with its predicate a % N = 0
  (ext/nested-parquet/synthetic/duckdb/selectivity.sql), N = 1, 10, ..., 10^6 - the selected rows are spread over the
  whole file
- selectivity_sorted: the data of generate_selectivity_data.py ("a" = row number) with a < 10^6 / N - the selected rows
  are contiguous

in the variants builtin (unnest), node (read_parquet_node with a join), flat (read_parquet_flat) and split (the paper's
pre-split files). Every query computes avg(greatest(a, b)) over the elements of the selected rows, like the paper's
split queries. N = 1 has no predicate. Query n<k> has N = 10^k.

Usage: make_selectivity_queries.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PREDICATES = {
    "selectivity_random": lambda n: f"a % {n} = 0",
    "selectivity_sorted": lambda n: f"a < {1_000_000 // n}",
}

VARIANTS = {
    "builtin": "SELECT avg(greatest(a, b)) FROM (SELECT a, unnest(b) AS b FROM 'l1.parquet'{where})",
    "node": "SELECT avg(greatest(r.a, e.b)) FROM read_parquet_node('l1.parquet') r "
    "JOIN read_parquet_node('l1.parquet', node := 'b') e ON e._ak0 = r._sk{where}",
    "flat": "SELECT avg(greatest(a, b)) FROM read_parquet_flat('l1.parquet'){where}",
    "split": "SELECT avg(greatest(a, b)) FROM 'normalized/l1_0.parquet' l0 "
    "JOIN 'normalized/l1_1.parquet' l1 ON l0._sk = l1._psk0{where}",
}

for directory, predicate in PREDICATES.items():
    path = os.path.join(HERE, "queries", directory)
    os.makedirs(path, exist_ok=True)
    for k in range(7):
        n = 10**k
        for variant, template in VARIANTS.items():
            condition = predicate(n).replace("a ", "r.a ", 1) if variant == "node" else predicate(n)
            where = "" if n == 1 else f" WHERE {condition}"
            with open(os.path.join(path, f"n{k}.{variant}.sql"), "w") as f:
                f.write(template.format(where=where) + ";\n")
