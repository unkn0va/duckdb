select c_custkey, c_name, sum(l_extendedprice * (1 - l_discount)) as revenue, c_acctbal, n_name, c_address, c_phone, c_comment
from read_parquet_node('nestedregion.parquet', node := 'r_nations') n join read_parquet_node('nestedregion.parquet', node := 'r_nations.n_customers') c on n._sk = c._ak1 join read_parquet_node('nestedregion.parquet', node := 'r_nations.n_customers.c_orders') o on c._sk = o._ak2 join read_parquet_node('nestedregion.parquet', node := 'r_nations.n_customers.c_orders.o_lineitems') l on o._sk = l._ak3
where o_orderdate >= date '1993-10-01' and o_orderdate < date '1993-10-01' + interval '3' month and l_returnflag = 'R'
group by c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment order by revenue desc limit 20
