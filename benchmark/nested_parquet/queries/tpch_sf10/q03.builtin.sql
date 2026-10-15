-- TPC-H Query 3
select
        o_orderkey,
        sum(l_extendedprice * (1 - l_discount)) as revenue,
        o_orderdate,
        o_shippriority
from
       (select c_mktsegment, o_orderkey, o_orderdate, o_shippriority, unnest(o_lineitems, recursive := true) from (select c_mktsegment, unnest(c_orders, recursive := true) from 'nestedcustomer.parquet'))
where
        c_mktsegment = 'BUILDING'
        and o_orderdate < date '1995-03-15'
        and l_shipdate > date '1995-03-15'
group by
        o_orderkey,
        o_orderdate,
        o_shippriority
order by
        revenue desc,
        o_orderdate
limit
        10
