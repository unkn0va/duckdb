select l_shipmode,
       sum(case when o_orderpriority = '1-URGENT' or o_orderpriority = '2-HIGH' then 1 else 0 end) as high_line_count,
       sum(case when o_orderpriority <> '1-URGENT' and o_orderpriority <> '2-HIGH' then 1 else 0 end) as low_line_count
from read_parquet_node('nestedregion.parquet', node := 'r_nations.n_customers.c_orders') o join read_parquet_node('nestedregion.parquet', node := 'r_nations.n_customers.c_orders.o_lineitems') l on o._sk = l._ak3
where l_shipmode in ('MAIL', 'SHIP') and l_commitdate < l_receiptdate and l_shipdate < l_commitdate
  and l_receiptdate >= date '1994-01-01' and l_receiptdate < date '1994-01-01' + interval '1' year
group by l_shipmode order by l_shipmode
