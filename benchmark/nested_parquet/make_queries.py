import os, re, sys

REPO = sys.argv[1]
OUT = sys.argv[2]


def copy(dataset_repo, name, qdir, builtin_file, normalized_file):
    os.makedirs(qdir, exist_ok=True)
    src = open(os.path.join(REPO, dataset_repo, "duckdb", builtin_file)).read()
    open(os.path.join(qdir, f"{name}.builtin.sql"), "w").write(src)
    norm = open(os.path.join(REPO, dataset_repo, "duckdb", "normalized", normalized_file)).read()
    norm = re.sub(r"'([A-Za-z0-9]+_?[0-9]+\.parquet)'", r"'normalized/\1'", norm)
    open(os.path.join(qdir, f"{name}.split.sql"), "w").write(norm)


def node(qdir, name, sql):
    open(os.path.join(qdir, f"{name}.node.sql"), "w").write(sql.strip() + "\n")


# ---------------- TPC-H SF10: customer -> orders -> lineitems ----------------
q = os.path.join(OUT, "tpch_sf10")
F = "'nestedcustomer.parquet'"
C = f"read_parquet_node({F})"
O = f"read_parquet_node({F}, node := 'c_orders')"
L = f"read_parquet_node({F}, node := 'c_orders.o_lineitems')"
for n in ["1", "3", "4", "6", "12"]:
    copy("nested-tpch-sf10", f"q{n:0>2}", q, f"{n}.sql", f"{n}normalized.sql")
Q1_BODY = """select l_returnflag, l_linestatus, sum(l_quantity) as sum_qty, sum(l_extendedprice) as sum_base_price,
       sum(l_extendedprice * (1 - l_discount)) as sum_disc_price, sum(l_extendedprice * (1 - l_discount) * (1 + l_tax)) as sum_charge,
       avg(l_quantity) as avg_qty, avg(l_extendedprice) as avg_price, avg(l_discount) as avg_disc, count(*) as count_order
from {L}
where l_shipdate <= date '1998-12-01' - interval '90' day
group by l_returnflag, l_linestatus order by l_returnflag, l_linestatus"""
Q6_BODY = """select sum(l_extendedprice * l_discount) as revenue
from {L}
where l_shipdate >= date '1994-01-01' and l_shipdate < date '1994-01-01' + interval '1' year
  and l_discount between 0.06 - 0.01 and 0.06 + 0.01 and l_quantity < 24"""
Q4_BODY = """select o_orderpriority, count(*) as order_count
from (select distinct o_orderkey, o_orderpriority
      from {O} o join {L} l on o._sk = l.{OL}
      where o_orderdate >= date '1993-07-01' and o_orderdate < date '1993-07-01' + interval '3' month
        and l_commitdate < l_receiptdate)
group by o_orderpriority order by o_orderpriority"""
Q12_BODY = """select l_shipmode,
       sum(case when o_orderpriority = '1-URGENT' or o_orderpriority = '2-HIGH' then 1 else 0 end) as high_line_count,
       sum(case when o_orderpriority <> '1-URGENT' and o_orderpriority <> '2-HIGH' then 1 else 0 end) as low_line_count
from {O} o join {L} l on o._sk = l.{OL}
where l_shipmode in ('MAIL', 'SHIP') and l_commitdate < l_receiptdate and l_shipdate < l_commitdate
  and l_receiptdate >= date '1994-01-01' and l_receiptdate < date '1994-01-01' + interval '1' year
group by l_shipmode order by l_shipmode"""
node(q, "q01", Q1_BODY.format(L=L))
node(q, "q06", Q6_BODY.format(L=L))
node(q, "q04", Q4_BODY.format(O=O, L=L, OL="_ak1"))
node(q, "q12", Q12_BODY.format(O=O, L=L, OL="_ak1"))
node(
    q,
    "q03",
    f"""select o_orderkey, sum(l_extendedprice * (1 - l_discount)) as revenue, o_orderdate, o_shippriority
from {C} c join {O} o on c._sk = o._ak0 join {L} l on o._sk = l._ak1
where c_mktsegment = 'BUILDING' and o_orderdate < date '1995-03-15' and l_shipdate > date '1995-03-15'
group by o_orderkey, o_orderdate, o_shippriority order by revenue desc, o_orderdate limit 10""",
)

# ---------------- TPC-H SF1: region -> nations -> customers -> orders -> lineitems ----------------
q = os.path.join(OUT, "tpch_sf1")
F = "'nestedregion.parquet'"
N = f"read_parquet_node({F}, node := 'r_nations')"
C = f"read_parquet_node({F}, node := 'r_nations.n_customers')"
O = f"read_parquet_node({F}, node := 'r_nations.n_customers.c_orders')"
L = f"read_parquet_node({F}, node := 'r_nations.n_customers.c_orders.o_lineitems')"
for n in ["1", "3", "4", "6", "10", "12"]:
    copy("nested-tpch", f"q{n:0>2}", q, f"{n}.sql", f"{n}normalized.sql")
node(q, "q01", Q1_BODY.format(L=L))
node(q, "q06", Q6_BODY.format(L=L))
node(q, "q04", Q4_BODY.format(O=O, L=L, OL="_ak3"))
node(q, "q12", Q12_BODY.format(O=O, L=L, OL="_ak3"))
node(
    q,
    "q03",
    f"""select l_orderkey, sum(l_extendedprice * (1 - l_discount)) as revenue, o_orderdate, o_shippriority
from {C} c join {O} o on c._sk = o._ak2 join {L} l on o._sk = l._ak3
where c_mktsegment = 'BUILDING' and o_orderdate < date '1995-03-15' and l_shipdate > date '1995-03-15'
group by l_orderkey, o_orderdate, o_shippriority order by revenue desc, o_orderdate limit 10""",
)
node(
    q,
    "q10",
    f"""select c_custkey, c_name, sum(l_extendedprice * (1 - l_discount)) as revenue, c_acctbal, n_name, c_address, c_phone, c_comment
from {N} n join {C} c on n._sk = c._ak1 join {O} o on c._sk = o._ak2 join {L} l on o._sk = l._ak3
where o_orderdate >= date '1993-10-01' and o_orderdate < date '1993-10-01' + interval '3' month and l_returnflag = 'R'
group by c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment order by revenue desc limit 20""",
)

# ---------------- DBLP: publication -> author ----------------
q = os.path.join(OUT, "dblp")
F = "'dblp.parquet'"
P = f"read_parquet_node({F})"
A = f"read_parquet_node({F}, node := 'author')"
for n in ["6", "7", "8", "9"]:
    copy("dblp", f"q{n:0>2}", q, f"{n}.sql", f"{n}normalized.sql")
node(q, "q06", f"select a.author as a, count(p.title) as b from {P} p join {A} a on p._sk = a._ak0 group by a.author")
node(
    q,
    "q07",
    f"select a.author, p.year, count(p.title) from {P} p join {A} a on p._sk = a._ak0 group by a.author, p.year",
)
node(
    q,
    "q08",
    f"""select a.author, p.year, count(p.title) from {P} p join {A} a on p._sk = a._ak0
where p.title like '%database%' and p.title like '%text%' and p.title like '%mining%' group by a.author, p.year""",
)
node(
    q,
    "q09",
    f"""select a.author, p.year, count(p.title) from {P} p join {A} a on p._sk = a._ak0
where p.title like '%database%' or p.title like '%text%' or p.title like '%mining%' group by a.author, p.year""",
)

# ---------------- XMark: open auctions -> bidders ----------------
q = os.path.join(OUT, "xmark")
F = "'sf10.parquet'"
OA = f"read_parquet_node({F}, node := 'open_auctions.open_auction')"
B = f"read_parquet_node({F}, node := 'open_auctions.open_auction.bidder')"
for n in ["2", "3", "4"]:
    copy("xmark", f"q{n:0>2}", q, f"{n}.sql", f"{n}normalized.sql")
# Q2: the authors' builtin query has a NULL row for every auction without bidders, which the flat, split and node
# forms join away - only the auctions with bidders, so that all forms compute the same result
open(os.path.join(q, "q02.builtin.sql"), "w").write(
    'select a.bidder[1].increase from (select unnest(open_auctions.open_auction) as a from "sf10.parquet") '
    "where len(a.bidder) > 0\n"
)
node(
    q,
    "q02",
    f"""select b.increase from {OA} a
join (select _ak1, first(increase order by _sk) as increase from {B} group by _ak1) b on a._sk = b._ak1""",
)
node(
    q,
    "q03",
    f"""select a._id as id, b.first, b.last from {OA} a
join (select _ak1, first(increase order by _sk) as first, last(increase order by _sk) as last from {B} group by _ak1) b on a._sk = b._ak1
where b.first * 2 <= b.last""",
)
node(
    q,
    "q04",
    f"""select a.reserve from {OA} a
join (select _ak1 from {B} group by _ak1
      having min(_sk) filter (where "personref._person" = 'person20') < min(_sk) filter (where "personref._person" = 'person51')) b
  on a._sk = b._ak1""",
)
