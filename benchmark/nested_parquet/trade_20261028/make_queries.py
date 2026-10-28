#!/usr/bin/env python3
"""Write the trade queries as <name>.builtin.sql (base / prenestoff / prenest), <name>.flat.sql (main_rey's
read_parquet_flat) and <name>.split.sql (pure flat: the pre-split files with stored keys, joined on sk = ak0) into
queries/. The paths are relative to a data folder of prepare_trade.sh (data/distinct or data/full).

The constants come from the value distribution of the 100M rows (the distinct rows weighted by their copies, see the
2-0 tables in README.md): c9 is trade number x 100,000, uniform over the trades; legs.value is roughly uniform.

Usage: make_queries.py [<out dir, default queries/ next to this script>]
"""
import os
import sys

OUT = (
    sys.argv[1]
    if __name__ == "__main__" and len(sys.argv) > 1
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries")
)

B = "'trade_B.parquet'"
A = "'trade_A.parquet'"
C = "'trade_C.parquet'"
PARENT = "'pureflat/parent.parquet'"
LEGS = "'pureflat/legs.parquet'"
CSA = "'../dims/csa_dictionary.parquet'"
PLOTS = "'../dims/date_plots_flat.parquet'"

# share of rows (c9) / of legs elements (value) that pass "< threshold"
C9 = {"01": 10_050_000, "10": 100_050_000, "50": 500_050_000, "90": 900_050_000, "100": 2_000_000_000}
VALUE = {"01": 12_500, "10": 103_200, "50": 507_400, "90": 911_200, "100": 2_000_000}
# value % 100 < k: about k% of the elements, not tied to the row (legs.value itself follows the trade number, like c9)
MOD = {"01": 1, "10": 10, "50": 50, "90": 90, "100": 100}
HALF = VALUE["50"]

QUERIES = {}


def legs_query(
    name,
    condition,
    flat_condition,
    split_condition,
    aggregate="sum(e.value)",
    flat_aggregate='sum("legs.value")',
    split_aggregate="sum(value)",
):
    """An aggregate over the legs elements that pass an element condition (no parent column)."""
    QUERIES[name] = (
        f"SELECT {aggregate} FROM (SELECT unnest(legs) AS e FROM {B}) WHERE {condition};",
        f"SELECT {flat_aggregate} FROM read_parquet_flat({B}) WHERE {flat_condition};",
        f"SELECT {split_aggregate} FROM {LEGS} WHERE {split_condition};",
    )


# Q1: top-level condition, every legs element of the passing rows
for share, threshold in C9.items():
    QUERIES[f"q1_s{share}"] = (
        f"SELECT sum(e.value) FROM (SELECT unnest(legs) AS e FROM {B} WHERE c9 < {threshold});",
        f'SELECT sum("legs.value") FROM read_parquet_flat({B}) WHERE c9 < {threshold};',
        f"SELECT sum(l.value) FROM {PARENT} p JOIN {LEGS} l ON p.sk = l.ak0 WHERE p.c9 < {threshold};",
    )

# Q2: element condition on legs.value; categorical: a common currency, a rare leg_id (no currency is rare)
for share, threshold in VALUE.items():
    legs_query(f"q2_s{share}", f"e.value < {threshold}", f'"legs.value" < {threshold}', f"value < {threshold}")
for share, k in MOD.items():
    legs_query(f"q2_m{share}", f"e.value % 100 < {k}", f'"legs.value" % 100 < {k}', f"value % 100 < {k}")
legs_query("q2_cat_common", "e.currency = 'AUD'", "\"legs.currency\" = 'AUD'", "currency = 'AUD'")
legs_query("q2_cat_rare", "e.leg_id = 'leg39'", "\"legs.leg_id\" = 'leg39'", "leg_id = 'leg39'")

# Q3: list length, element condition passing about half of the elements (legs: q2_s50)
for name, condition in (("c13", "> 0"), ("c12", "< 8022"), ("c11", "< 39264604")):
    QUERIES[f"q3_{name}"] = (
        f"SELECT sum(v) FROM (SELECT unnest({name}) AS v FROM {B}) WHERE v {condition};",
        f"SELECT sum({name}) FROM read_parquet_flat({B}) WHERE {name} {condition};",
        f"SELECT sum({name}) FROM 'pureflat/{name}.parquet' WHERE {name} {condition};",
    )

# Q3w: Q3 on C, where c11..c13 are LIST<STRUCT<v>> - pre-nest only takes predicates on fields of struct elements
for name, condition in (("c13", "> 0"), ("c12", "< 8022"), ("c11", "< 39264604")):
    QUERIES[f"q3w_{name}"] = (
        f"SELECT sum(e.v) FROM (SELECT unnest({name}) AS e FROM {C}) WHERE e.v {condition};",
        f'SELECT sum("{name}.v") FROM read_parquet_flat({C}) WHERE "{name}.v" {condition};',
        f"SELECT sum({name}) FROM 'pureflat/{name}.parquet' WHERE {name} {condition};",
    )

# Q4: number of unnested lists, on A; two sibling lists = every pair of their elements within a row. The builtin query
# unnests each list with the row number and joins on it (an UNNEST of both in one SELECT would pair them by position).
QUERIES["q4_one"] = (
    f"SELECT count(*), sum(v) FROM (SELECT unnest(c11) AS v FROM {A});",
    f"SELECT count(*), sum(c11) FROM read_parquet_flat({A});",
    "SELECT count(*), sum(c11) FROM 'pureflat/c11.parquet';",
)
QUERIES["q4_two"] = (
    f"SELECT count(*), sum(a.v), sum(length(b.s))\n"
    f"FROM (SELECT file_row_number AS rn, unnest(c11) AS v FROM read_parquet({A}, file_row_number = true)) a\n"
    f"JOIN (SELECT file_row_number AS rn, unnest(c14) AS s FROM read_parquet({A}, file_row_number = true)) b ON a.rn = b.rn;",
    f"SELECT count(*), sum(c11), sum(length(c14)) FROM read_parquet_flat({A});",
    "SELECT count(*), sum(a.c11), sum(length(b.c14)) FROM 'pureflat/c11.parquet' a JOIN 'pureflat/c14.parquet' b ON a.ak0 = b.ak0;",
)

# Q5: OR over two fields of an element
legs_query(
    "q5_or",
    "e.currency = 'AUD' OR e.option_type = 'put'",
    "\"legs.currency\" = 'AUD' OR \"legs.option_type\" = 'put'",
    "currency = 'AUD' OR option_type = 'put'",
)

# Q6: aggregate kind with the condition of q2_s50 (SUM = q2_s50)
legs_query(
    "q6_count", f"e.value < {HALF}", f'"legs.value" < {HALF}', f"value < {HALF}", "count(*)", "count(*)", "count(*)"
)
QUERIES["q6_group"] = (
    f"SELECT c5, sum(e.value) FROM (SELECT c5, unnest(legs) AS e FROM {B}) WHERE e.value < {HALF} GROUP BY c5 ORDER BY c5;",
    f'SELECT c5, sum("legs.value") FROM read_parquet_flat({B}) WHERE "legs.value" < {HALF} GROUP BY c5 ORDER BY c5;',
    f"SELECT p.c5, sum(l.value) FROM {PARENT} p JOIN {LEGS} l ON p.sk = l.ak0 WHERE l.value < {HALF} GROUP BY p.c5 ORDER BY p.c5;",
)

# Q7: the unnested legs joined with a dimension table
QUERIES["q7_csa"] = (
    f"SELECT d.csa, count(*), sum(t.e.value) FROM (SELECT c0, c1, unnest(legs) AS e FROM {B}) t\n"
    f"JOIN {CSA} d ON t.c0 = d.as_of_date AND t.c1 = d.csa_hash GROUP BY d.csa ORDER BY d.csa;",
    f'SELECT d.csa, count(*), sum(t."legs.value") FROM read_parquet_flat({B}) t\n'
    f"JOIN {CSA} d ON t.c0 = d.as_of_date AND t.c1 = d.csa_hash GROUP BY d.csa ORDER BY d.csa;",
    f"SELECT d.csa, count(*), sum(l.value) FROM {PARENT} p JOIN {LEGS} l ON p.sk = l.ak0\n"
    f"JOIN {CSA} d ON p.c0 = d.as_of_date AND p.c1 = d.csa_hash GROUP BY d.csa ORDER BY d.csa;",
)
QUERIES["q7_plots"] = (
    f"SELECT d.reg_scenario, count(*), sum(t.e.value) FROM (SELECT c8, unnest(legs) AS e FROM {B}) t\n"
    f"JOIN {PLOTS} d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;",
    f'SELECT d.reg_scenario, count(*), sum(t."legs.value") FROM read_parquet_flat({B}) t\n'
    f"JOIN {PLOTS} d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;",
    f"SELECT d.reg_scenario, count(*), sum(l.value) FROM {PARENT} p JOIN {LEGS} l ON p.sk = l.ak0\n"
    f"JOIN {PLOTS} d ON p.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;",
)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        if name.endswith(".sql"):
            os.remove(os.path.join(OUT, name))
    for name, texts in QUERIES.items():
        for variant, text in zip(("builtin", "flat", "split"), texts):
            with open(os.path.join(OUT, f"{name}.{variant}.sql"), "w") as f:
                f.write(text + "\n")
    print(f"{len(QUERIES)} queries x 3 variants -> {OUT}")
