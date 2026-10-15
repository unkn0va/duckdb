-- TPC-H Query 3
select
        "c_orders-o_orderkey",
        sum("c_orders-o_lineitems-l_extendedprice" * (1 - "c_orders-o_lineitems-l_discount")) as revenue,
        "c_orders-o_orderdate",
        "c_orders-o_shippriority"
from
        'normalized/nestedcustomer_0.parquet' c inner join 'normalized/nestedcustomer_1.parquet' o on c._sk = o._psk0 inner join 'normalized/nestedcustomer_2.parquet' l on o._sk = l._psk1
where
        "c_mktsegment" = 'BUILDING'
        and "c_orders-o_orderdate" < date '1995-03-15'
        and "c_orders-o_lineitems-l_shipdate" > date '1995-03-15'
group by
        "c_orders-o_orderkey",
        "c_orders-o_orderdate",
        "c_orders-o_shippriority"
order by
        revenue desc,
        "c_orders-o_orderdate"
limit
        10
