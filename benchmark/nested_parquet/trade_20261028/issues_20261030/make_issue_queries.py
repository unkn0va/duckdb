#!/usr/bin/env python3
"""Write the queries of issues 1-1 and 2-1 next to this script (paths relative to a data folder of prepare_trade.sh).

queries_stage/<stage>.<variant>.sql - legs of trade_B, stopped after one step of the work (issue 1-1):
  s1_box     the lists only:       sum(len(legs))  | flat: the keys of the legs node | pure flat: the stored key ak0
  s2_unnest  the element rows:     count(*) after UNNEST | flat, pure flat: count of leg_id and value
  s2f_fields s2 with the fields of s3 read: count(e.leg_id), count(e.value) - prenest prunes the other struct fields
             only when fields are referenced, so s2_unnest reads all four and s3 two (flat, pure flat: = s2_unnest)
  s3_cond    the condition of q2_c50 on leg_id and the sum of value (= q2_c50)
  Pure flat answers count(column) from the metadata unless statistics_propagation is off (a leading SET of s1/s2).

queries_plans/<query>.<form>.<variant>.sql - q1_s01, q1_s50, q6_group, q7_csa, q7_plots (issue 2-1):
  orig    the query of ../queries
  fixed   the join order fixed: join_order off and the joins written elements -> parent -> dimension table; the build
          side is still chosen by build_side_probe_side. builtin and flat keep their text (their only joins are the
          dimension join and the joins inside read_parquet_flat)
  preagg  the aggregation before the dimension join (q7_csa: by c0, c1; q7_plots: by c8), in every configuration.
          q1 and q6 have no dimension join - aggregating per parent before the parent-child join is not written

queries_build/q4_two.{orig,small_build}.builtin.sql - q4_two with the smaller unnested list (c14) built (issue 2-2)

Usage: make_issue_queries.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from make_queries import B, CSA, LEGS, PARENT, PLOTS, QUERIES, RANGE  # noqa: E402

FLAT = f"read_parquet_flat({B})"
NO_STATS = "SET disabled_optimizers = 'statistics_propagation';\n"
FIXED = "SET disabled_optimizers = 'join_order';\n"
VARIANTS = ("builtin", "flat", "split")

STAGES = {
    "s1_box": (
        f"SELECT sum(len(legs)) FROM {B};",
        f'SELECT count("legs._sk") FROM {FLAT};',
        f"{NO_STATS}SELECT count(ak0) FROM {LEGS};",
    ),
    "s2_unnest": (
        f"SELECT count(*), count(*) FROM (SELECT unnest(legs) AS e FROM {B});",
        f'SELECT count("legs.leg_id"), count("legs.value") FROM {FLAT};',
        f"{NO_STATS}SELECT count(leg_id), count(value) FROM {LEGS};",
    ),
    "s2f_fields": (
        f"SELECT count(e.leg_id), count(e.value) FROM (SELECT unnest(legs) AS e FROM {B});",
        f'SELECT count("legs.leg_id"), count("legs.value") FROM {FLAT};',
        f"{NO_STATS}SELECT count(leg_id), count(value) FROM {LEGS};",
    ),
    "s3_cond": QUERIES["q2_c50"],
}
assert f"'{RANGE['50']}'" in STAGES["s3_cond"][0]

ELEMENTS_FIRST = f"{LEGS} l JOIN {PARENT} p ON l.ak0 = p.sk"
PLANS = {}
for q in ("q1_s01", "q1_s50", "q6_group", "q7_csa", "q7_plots"):
    PLANS[(q, "orig")] = QUERIES[q]
    builtin, flat, split = QUERIES[q]
    PLANS[(q, "fixed")] = (
        FIXED + builtin,
        FIXED + flat,
        FIXED + split.replace(f"{PARENT} p JOIN {LEGS} l ON p.sk = l.ak0", ELEMENTS_FIRST),
    )
    assert ELEMENTS_FIRST in PLANS[(q, "fixed")][2], q

PLANS[("q7_csa", "preagg")] = tuple(
    f"SELECT d.csa, sum(t.n), sum(t.s) FROM (SELECT c0, c1, count(*) AS n, sum({value}) AS s FROM {source} GROUP BY c0, c1) t\n"
    f"JOIN {CSA} d ON t.c0 = d.as_of_date AND t.c1 = d.csa_hash GROUP BY d.csa ORDER BY d.csa;"
    for value, source in (
        ("e.value", f"(SELECT c0, c1, unnest(legs) AS e FROM {B})"),
        ('"legs.value"', FLAT),
        ("value", f"(SELECT p.c0, p.c1, l.value FROM {ELEMENTS_FIRST})"),
    )
)
PLANS[("q7_plots", "preagg")] = tuple(
    f"SELECT d.reg_scenario, sum(t.n), sum(t.s) FROM (SELECT c8, count(*) AS n, sum({value}) AS s FROM {source} GROUP BY c8) t\n"
    f"JOIN {PLOTS} d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;"
    for value, source in (
        ("e.value", f"(SELECT c8, unnest(legs) AS e FROM {B})"),
        ('"legs.value"', FLAT),
        ("value", f"(SELECT p.c8, l.value FROM {ELEMENTS_FIRST})"),
    )
)


# q4_two (issue 2-2): both UNNESTs are estimated at the rows of the file, so build_side_probe_side cannot tell that
# c11 (6.7 elements per row) is larger than c14 (2.5); with it off the second side of the text, c14, is built
BUILD = {
    "q4_two.orig": (QUERIES["q4_two"][0],),
    "q4_two.small_build": ("SET disabled_optimizers = 'build_side_probe_side';\n" + QUERIES["q4_two"][0],),
}


def write(folder, queries):
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if name.endswith(".sql"):
            os.remove(os.path.join(folder, name))
    for name, texts in queries.items():
        for variant, text in zip(VARIANTS, texts):
            with open(os.path.join(folder, f"{name}.{variant}.sql"), "w") as f:
                f.write(text + "\n")


if __name__ == "__main__":
    write(os.path.join(HERE, "queries_stage"), STAGES)
    write(os.path.join(HERE, "queries_plans"), {f"{q}.{form}": texts for (q, form), texts in PLANS.items()})
    write(os.path.join(HERE, "queries_build"), BUILD)
    print(f"{len(STAGES)} stages, {len(PLANS)} plan variants x 3 -> {HERE}/queries_stage, queries_plans")
