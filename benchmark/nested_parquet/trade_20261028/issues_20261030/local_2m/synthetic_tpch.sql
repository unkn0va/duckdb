-- a small synthetic nested TPC-H with the schema of the paper's files (test data only); a third of the customers
-- have no orders (empty c_orders), as in TPC-H
SET threads = 8;
CREATE TABLE li AS
SELECT o AS l_orderkey, ln AS l_linenumber, (hash(o, ln) % 1000000007)::BIGINT AS h FROM range(0, 150000) r(o), range(1, 8) t(ln)
WHERE (o // 10) % 3 <> 0 AND ln <= 1 + o % 7;
CREATE TABLE lis AS
SELECT l_orderkey, list(struct_pack(
  l_orderkey := l_orderkey, l_partkey := (h % 200000)::BIGINT, l_suppkey := (h % 10000)::BIGINT, l_linenumber := l_linenumber,
  l_quantity := (h % 50 + 1)::DOUBLE, l_extendedprice := (h % 100000)::DOUBLE / 7, l_discount := (h % 11)::DOUBLE / 100,
  l_tax := (h % 9)::DOUBLE / 100, l_returnflag := ['A', 'N', 'R'][h % 3 + 1], l_linestatus := ['O', 'F'][h % 2 + 1],
  l_shipdate := DATE '1992-01-01' + (h % 2500)::INT, l_commitdate := DATE '1992-01-01' + (h % 2490)::INT,
  l_receiptdate := DATE '1992-01-10' + (h % 2500)::INT, l_shipinstruct := 'DELIVER IN PERSON', l_shipmode := ['MAIL', 'SHIP', 'AIR'][h % 3 + 1],
  l_comment := 'c' || h % 1000) ORDER BY l_linenumber) AS o_lineitems
FROM li GROUP BY l_orderkey;
CREATE TABLE ord AS
SELECT o AS o_orderkey, o // 10 AS o_custkey, (hash(o) % 1000000007)::BIGINT AS h FROM range(0, 150000) r(o) WHERE (o // 10) % 3 <> 0;
CREATE TABLE ords AS
SELECT o_custkey, list(struct_pack(o_orderkey := o_orderkey, o_custkey := o_custkey, o_orderstatus := ['O', 'F', 'P'][h % 3 + 1],
  o_totalprice := (h % 500000)::DOUBLE / 3, o_orderdate := DATE '1992-01-01' + (h % 2400)::INT,
  o_orderpriority := ['1-URGENT', '2-HIGH', '3-MEDIUM', '4-NOT SPECIFIED', '5-LOW'][h % 5 + 1], o_clerk := 'Clerk#' || h % 1000,
  o_shippriority := 0::BIGINT, o_comment := 'o' || h % 1000, o_lineitems := lis.o_lineitems) ORDER BY o_orderkey) AS c_orders
FROM ord JOIN lis ON l_orderkey = o_orderkey GROUP BY o_custkey;
CREATE TABLE cust AS
SELECT c AS c_custkey, 'Customer#' || c AS c_name, 'addr' || c AS c_address, c % 25 AS c_nationkey, '10-' || c AS c_phone,
  (hash(c) % 10000)::DOUBLE / 3 AS c_acctbal, ['BUILDING', 'AUTOMOBILE', 'MACHINERY', 'HOUSEHOLD', 'FURNITURE'][(hash(c) % 5)::BIGINT + 1] AS c_mktsegment,
  'cc' || c AS c_comment, coalesce(c_orders, []) AS c_orders
FROM range(0, 15000) r(c) LEFT JOIN ords ON o_custkey = c;
COPY (SELECT * FROM cust ORDER BY c_custkey) TO '<test data folder>/nested-parquet-datasets/nested-tpch-sf10/nestedcustomer.parquet' (FORMAT parquet, ROW_GROUP_SIZE 4096);
CREATE TABLE nat AS
SELECT c_nationkey AS n_nationkey, list(struct_pack(c_custkey, c_name, c_address, c_nationkey, c_phone, c_acctbal, c_mktsegment, c_comment, c_orders) ORDER BY c_custkey) AS n_customers
FROM cust GROUP BY c_nationkey;
COPY (
  SELECT r AS r_regionkey, 'REGION' || r AS r_name, 'rc' || r AS r_comment, r AS __index_level_0__,
    list(struct_pack(n_comment := 'nc' || n_nationkey, n_name := 'NATION' || n_nationkey, n_nationkey := n_nationkey, n_customers := n_customers) ORDER BY n_nationkey) AS r_nations
  FROM range(5) t(r) JOIN nat ON n_nationkey % 5 = r GROUP BY r ORDER BY r
) TO '<test data folder>/nested-parquet-datasets/nested-tpch/nestedregion.parquet' (FORMAT parquet);
