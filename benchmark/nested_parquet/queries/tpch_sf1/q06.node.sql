select sum(l_extendedprice * l_discount) as revenue
from read_parquet_node('nestedregion.parquet', node := 'r_nations.n_customers.c_orders.o_lineitems')
where l_shipdate >= date '1994-01-01' and l_shipdate < date '1994-01-01' + interval '1' year
  and l_discount between 0.06 - 0.01 and 0.06 + 0.01 and l_quantity < 24
