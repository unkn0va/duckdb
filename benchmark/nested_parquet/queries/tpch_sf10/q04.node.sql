select o_orderpriority, count(*) as order_count
from (select distinct o_orderkey, o_orderpriority
      from read_parquet_node('nestedcustomer.parquet', node := 'c_orders') o join read_parquet_node('nestedcustomer.parquet', node := 'c_orders.o_lineitems') l on o._sk = l._ak1
      where o_orderdate >= date '1993-07-01' and o_orderdate < date '1993-07-01' + interval '3' month
        and l_commitdate < l_receiptdate)
group by o_orderpriority order by o_orderpriority
