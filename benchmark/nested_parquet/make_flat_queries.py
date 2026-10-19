import os, re, subprocess, sys

DUCKDB, DATA, OUT = sys.argv[1], sys.argv[2], sys.argv[3]


def flat_subquery(data_dir, file):
    out = subprocess.run(
        [
            DUCKDB,
            "-no-agent",
            "-csv",
            "-noheader",
            "-c",
            f"SELECT column_name FROM (DESCRIBE FROM read_parquet_flat('{file}'))",
        ],
        capture_output=True,
        text=True,
        cwd=data_dir,
        check=True,
    ).stdout.split()
    aliases = {}
    for path in out:
        short = path.split(".")[-1]
        assert short not in aliases, short
        aliases[short] = path
    cols = ", ".join(f'"{p}" AS {s}' for s, p in aliases.items())
    return f"(SELECT {cols} FROM read_parquet_flat('{file}'))"


def write(qdir, name, sql):
    open(os.path.join(qdir, f"{name}.flat.sql"), "w").write(sql.strip() + "\n")


for qname, ddir, file in [
    ("tpch_sf10", "nested-tpch-sf10", "nestedcustomer.parquet"),
    ("tpch_sf1", "nested-tpch", "nestedregion.parquet"),
]:
    F = flat_subquery(os.path.join(DATA, ddir), file)
    qdir = os.path.join(OUT, qname)
    write(
        qdir,
        "q01",
        f"""select l_returnflag, l_linestatus, sum(l_quantity) as sum_qty, sum(l_extendedprice) as sum_base_price,
       sum(l_extendedprice * (1 - l_discount)) as sum_disc_price, sum(l_extendedprice * (1 - l_discount) * (1 + l_tax)) as sum_charge,
       avg(l_quantity) as avg_qty, avg(l_extendedprice) as avg_price, avg(l_discount) as avg_disc, count(*) as count_order
from {F} where l_shipdate <= date '1998-12-01' - interval '90' day
group by l_returnflag, l_linestatus order by l_returnflag, l_linestatus""",
    )
    write(
        qdir,
        "q06",
        f"""select sum(l_extendedprice * l_discount) as revenue from {F}
where l_shipdate >= date '1994-01-01' and l_shipdate < date '1994-01-01' + interval '1' year
  and l_discount between 0.06 - 0.01 and 0.06 + 0.01 and l_quantity < 24""",
    )
    write(
        qdir,
        "q04",
        f"""select o_orderpriority, count(*) as order_count
from (select distinct o_orderkey, o_orderpriority from {F}
      where o_orderdate >= date '1993-07-01' and o_orderdate < date '1993-07-01' + interval '3' month and l_commitdate < l_receiptdate)
group by o_orderpriority order by o_orderpriority""",
    )
    write(
        qdir,
        "q12",
        f"""select l_shipmode,
       sum(case when o_orderpriority = '1-URGENT' or o_orderpriority = '2-HIGH' then 1 else 0 end) as high_line_count,
       sum(case when o_orderpriority <> '1-URGENT' and o_orderpriority <> '2-HIGH' then 1 else 0 end) as low_line_count
from {F}
where l_shipmode in ('MAIL', 'SHIP') and l_commitdate < l_receiptdate and l_shipdate < l_commitdate
  and l_receiptdate >= date '1994-01-01' and l_receiptdate < date '1994-01-01' + interval '1' year
group by l_shipmode order by l_shipmode""",
    )
    key = "o_orderkey" if qname == "tpch_sf10" else "l_orderkey"
    write(
        qdir,
        "q03",
        f"""select {key}, sum(l_extendedprice * (1 - l_discount)) as revenue, o_orderdate, o_shippriority from {F}
where c_mktsegment = 'BUILDING' and o_orderdate < date '1995-03-15' and l_shipdate > date '1995-03-15'
group by {key}, o_orderdate, o_shippriority order by revenue desc, o_orderdate limit 10""",
    )
    if qname == "tpch_sf1":
        write(
            qdir,
            "q10",
            f"""select c_custkey, c_name, sum(l_extendedprice * (1 - l_discount)) as revenue, c_acctbal, n_name, c_address, c_phone, c_comment
from {F} where o_orderdate >= date '1993-10-01' and o_orderdate < date '1993-10-01' + interval '3' month and l_returnflag = 'R'
group by c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment order by revenue desc limit 20""",
        )

F = flat_subquery(os.path.join(DATA, "dblp"), "dblp.parquet")
qdir = os.path.join(OUT, "dblp")
write(qdir, "q06", f"select author as a, count(title) as b from {F} group by author")
write(qdir, "q07", f"select author, year, count(title) from {F} group by author, year")
write(
    qdir,
    "q08",
    f"select author, year, count(title) from {F} where title like '%database%' and title like '%text%' and title like '%mining%' group by author, year",
)
write(
    qdir,
    "q09",
    f"select author, year, count(title) from {F} where title like '%database%' or title like '%text%' or title like '%mining%' group by author, year",
)
