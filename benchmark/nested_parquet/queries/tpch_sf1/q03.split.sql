-- TPC-H Query 3
select
        "r_nations-n_customers-c_orders-o_orderkey" as a,
        sum("r_nations-n_customers-c_orders-o_lineitems-l_extendedprice" * (1 - "r_nations-n_customers-c_orders-o_lineitems-l_discount")) as b,
        "r_nations-n_customers-c_orders-o_orderdate" as c,
        "r_nations-n_customers-c_orders-o_shippriority" as d
from
        'normalized/nestedregion_2.parquet' c inner join 'normalized/nestedregion_3.parquet' o on c._sk = o._psk2 inner join 'normalized/nestedregion_4.parquet' l on o._sk = l._psk3
where
        "r_nations-n_customers-c_mktsegment" = 'BUILDING'
        and "r_nations-n_customers-c_orders-o_orderdate" < date '1995-03-15'
        and "r_nations-n_customers-c_orders-o_lineitems-l_shipdate" > date '1995-03-15'
group by
        "r_nations-n_customers-c_orders-o_orderkey",
        "r_nations-n_customers-c_orders-o_orderdate",
        "r_nations-n_customers-c_orders-o_shippriority"
order by
        b desc,
        "r_nations-n_customers-c_orders-o_orderdate"
limit
        10
