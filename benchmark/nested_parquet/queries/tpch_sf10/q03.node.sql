select o_orderkey, sum(l_extendedprice * (1 - l_discount)) as revenue, o_orderdate, o_shippriority
from read_parquet_node('nestedcustomer.parquet') c join read_parquet_node('nestedcustomer.parquet', node := 'c_orders') o on c._sk = o._ak0 join read_parquet_node('nestedcustomer.parquet', node := 'c_orders.o_lineitems') l on o._sk = l._ak1
where c_mktsegment = 'BUILDING' and o_orderdate < date '1995-03-15' and l_shipdate > date '1995-03-15'
group by o_orderkey, o_orderdate, o_shippriority order by revenue desc, o_orderdate limit 10
