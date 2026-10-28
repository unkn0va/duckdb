#!/usr/bin/env python3
"""The actual selectivity of every trade query: the share of the top-level rows that contribute to the result, and
the share of the elements of the unnested list that pass (q4_two / q7_plots: the result rows per element instead).

Computed on A-shaped rows (c11..c18 as separate lists) with a weight n per row: either work/distinct.parquet of
prepare_trade.sh (the distinct rows with their number of copies - exactly the 100M rows) or any trade_A.parquet
(n = 1).

Usage: selectivity.py <duckdb> <work/distinct.parquet | trade_A.parquet> [--csa <csa_dictionary.parquet>]
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_queries import C9, HALF, MOD, VALUE  # noqa: E402

duckdb, source = sys.argv[1], sys.argv[2]
csa = (
    sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.path.dirname(source), "..", "dims", "csa_dictionary.parquet")
)


FIELDS = {"leg_id": "c15[i + 1]", "currency": "c16[i + 1]", "option_type": "c17[i + 1]", "value": "c18[i + 1]"}


def legs(condition):
    """Passing legs elements of a row, for a condition on {leg_id}, {currency}, {option_type} and {value}."""
    return f"len(list_filter(range(len(c18)), lambda i: {condition.format(**FIELDS)}))"


def row(name, passing_rows, passing_elements, all_elements):
    return (
        f"SELECT '{name}' AS query, round(100 * sum(n * ({passing_rows})::INT) / sum(n), 3) AS rows_pct, "
        f"round(100 * sum(n * ({passing_elements})) / sum(n * ({all_elements})), 3) AS elements_pct FROM t"
    )


parts = []
for share, threshold in C9.items():
    parts.append(
        row(f"q1_s{share}", f"c9 < {threshold}", f"CASE WHEN c9 < {threshold} THEN len(c18) ELSE 0 END", "len(c18)")
    )
for share, threshold in VALUE.items():
    parts.append(
        row(
            f"q2_s{share}",
            f"{legs('{value} < ' + str(threshold))} > 0",
            legs("{value} < " + str(threshold)),
            "len(c18)",
        )
    )
for share, k in MOD.items():
    condition = "{value} % 100 < " + str(k)
    parts.append(row(f"q2_m{share}", f"{legs(condition)} > 0", legs(condition), "len(c18)"))
for name, condition in (
    ("q2_cat_common", "{currency} = 'AUD'"),
    ("q2_cat_rare", "{leg_id} = 'leg39'"),
    ("q5_or", "{currency} = 'AUD' OR {option_type} = 'put'"),
    ("q6_count, q6_group", "{value} < " + str(HALF)),
):
    parts.append(row(name, f"{legs(condition)} > 0", legs(condition), "len(c18)"))
for name, condition in (("c13", "> 0"), ("c12", "< 8022"), ("c11", "< 39264604")):
    passing = f"len(list_filter({name}, lambda x: x {condition}))"
    parts.append(row(f"q3_{name}, q3w_{name}", f"{passing} > 0", passing, f"len({name})"))
parts.append(row("q4_one", "true", "len(c11)", "len(c11)"))
parts.append(row("q4_two (pairs per c11 element)", "true", "len(c11) * len(c14)", "len(c11)"))
in_csa = f"(c0, c1) IN (SELECT (as_of_date, csa_hash) FROM '{csa}')"
parts.append(row("q7_csa", in_csa, f"CASE WHEN {in_csa} THEN len(c18) ELSE 0 END", "len(c18)"))
plots = "(SELECT len(plot_dates) FROM '" + csa.replace("csa_dictionary", "date_plots") + "' WHERE reg_scenario = c8)"
parts.append(row("q7_plots (result rows per element)", "true", f"len(c18) * {plots}", "len(c18)"))

weight = "n" if "distinct" in os.path.basename(source) else "1 AS n"
sql = f"CREATE VIEW t AS SELECT *, {weight} FROM '{source}';\n" + "\nUNION ALL\n".join(parts) + ";"
run = subprocess.run([duckdb, "-no-agent", "-markdown", "-c", sql], capture_output=True, text=True)
print(run.stdout or run.stderr)
