select c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice,
       sum(l.l_quantity) as sum_qty
from (
    select c_custkey, c_name,
           o.o_orderkey as o_orderkey,
           o.o_orderdate as o_orderdate,
           o.o_totalprice as o_totalprice,
           unnest(o.o_lineitems) as l
    from (select c_custkey, c_name, unnest(c_orders) as o from '/home/layun03/data/tpch-nested/1/customer.parquet')
)
group by c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice
having sum(l.l_quantity) > 313
order by o_totalprice desc, o_orderdate
limit 100
