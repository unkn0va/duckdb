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

queries_bn/ - the cost of the NULL copies of pruned struct fields (follow-up A): q2_s50 on trade_B (.orig) and on
  trade_Bn1 (legs = LIST<STRUCT<value>>, .bn1); q2_c50 on trade_B (.orig) and on trade_Bn2 (leg_id, value; .bn2)

queries_fanout/<storage>_k<k>.<orig|preagg>.<variant>.sql - q7_plots' shape on a dimension table with k dates per
  scenario (dims_k/dim_k<k>.parquet, k = 1, 2, 4, 8, 16; follow-up D), as written and with the aggregation before
  the dimension join, in three storages: a = fact and dimension parquet, b = fact parquet and the dimension a DuckDB
  table, c = both DuckDB tables (fanout/fanout.duckdb, attached read-only; no flat query - read_parquet_flat reads
  parquet only)

queries_sorted/q2_c50.{orig,sorted} - q2_c50 on trade_B and on trade_Bsorted (the same rows, legs sorted by leg_id
  and rows by their smallest leg_id), builtin and flat (follow-up G1)
queries_stage_db/<stage>.builtin.sql - s1_box, s2_unnest, s3_cond on the DuckDB table fw.trade_b of
  fanout/fanout.duckdb (follow-up G3; compare with queries_stage/ on parquet)
queries_syn/syn_L<L> - q3's shape on synthetic files ../syn/syn_L<L>.parquet with one BIGINT list of length L per
  row (L = 1, 2, 4, 8, 16, 32; make_syn.py), condition v < 500000 (about half), builtin and flat (follow-up G4)

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


BN = {}
for q, file, name in (("q2_s50", "trade_Bn1.parquet", "bn1"), ("q2_c50", "trade_Bn2.parquet", "bn2")):
    BN[f"{q}.orig"] = QUERIES[q][:2]
    BN[f"{q}.{name}"] = tuple(t.replace(B, f"'{file}'") for t in QUERIES[q][:2])
    assert all(f"'{file}'" in t for t in BN[f"{q}.{name}"])

ATTACH = "ATTACH '../fanout/fanout.duckdb' AS fw (READ_ONLY);\n"
FANOUT_K = (1, 2, 4, 8, 16)
FANOUT = {}
for k in FANOUT_K:
    dim = f"'../dims_k/dim_k{k}.parquet'"
    for form, texts in (("orig", QUERIES["q7_plots"]), ("preagg", PLANS[("q7_plots", "preagg")])):
        a = tuple(t.replace(PLOTS, dim) for t in texts)
        assert all(dim in t for t in a)
        b = tuple(ATTACH + t.replace(dim, f"fw.dim_k{k}") for t in a)
        c = tuple(
            t.replace(B, "fw.trade_b").replace(PARENT, "fw.parent").replace(LEGS, "fw.legs") for t in (b[0], b[2])
        )
        FANOUT[f"a_k{k:02d}.{form}"] = a
        FANOUT[f"b_k{k:02d}.{form}"] = b
        FANOUT[f"c_k{k:02d}.{form}"] = (c[0], None, c[1])


SORTED = {
    "q2_c50.orig": QUERIES["q2_c50"][:2],
    "q2_c50.sorted": tuple(t.replace(B, "'trade_Bsorted.parquet'") for t in QUERIES["q2_c50"][:2]),
}
STAGE_DB = {name: (ATTACH + texts[0].replace(B, "fw.trade_b"),) for name, texts in STAGES.items()
            if name in ("s1_box", "s2_unnest", "s3_cond")}
assert all("fw.trade_b" in t[0] for t in STAGE_DB.values())
SYN_L = (1, 2, 4, 8, 16, 32)
SYN = {
    f"syn_L{n:02d}": (
        f"SELECT sum(v) FROM (SELECT unnest(c) AS v FROM '../syn/syn_L{n}.parquet') WHERE v < 500000;",
        f"SELECT sum(c) FROM read_parquet_flat('../syn/syn_L{n}.parquet') WHERE c < 500000;",
    )
    for n in SYN_L
}


def write(folder, queries):
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if name.endswith(".sql"):
            os.remove(os.path.join(folder, name))
    for name, texts in queries.items():
        for variant, text in zip(VARIANTS, texts):
            if text is None:
                continue
            with open(os.path.join(folder, f"{name}.{variant}.sql"), "w") as f:
                f.write(text + "\n")


if __name__ == "__main__":
    write(os.path.join(HERE, "queries_stage"), STAGES)
    write(os.path.join(HERE, "queries_plans"), {f"{q}.{form}": texts for (q, form), texts in PLANS.items()})
    write(os.path.join(HERE, "queries_build"), BUILD)
    write(os.path.join(HERE, "queries_bn"), BN)
    write(os.path.join(HERE, "queries_fanout"), FANOUT)
    write(os.path.join(HERE, "queries_sorted"), SORTED)
    write(os.path.join(HERE, "queries_stage_db"), STAGE_DB)
    write(os.path.join(HERE, "queries_syn"), SYN)
    print(f"{len(STAGES)} stages, {len(PLANS)} plan variants x 3 -> {HERE}/queries_stage, queries_plans")
