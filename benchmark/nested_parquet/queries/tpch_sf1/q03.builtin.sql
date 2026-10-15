-- TPC-H Query 3
select
        l_orderkey,
        sum(l_extendedprice * (1 - l_discount)) as revenue,
        o_orderdate,
        o_shippriority
from
       (select c_mktsegment, o_orderdate, o_shippriority, unnest(o_lineitems, recursive := true) from (select c_mktsegment, unnest(c_orders, recursive := true) from (select unnest(n_customers, recursive := true) from (select unnest(r_nations, recursive := true) from 'nestedregion.parquet'))))
where
        c_mktsegment = 'BUILDING'
        and o_orderdate < date '1995-03-15'
        and l_shipdate > date '1995-03-15'
group by
        l_orderkey,
        o_orderdate,
        o_shippriority
order by
        revenue desc,
        o_orderdate
limit
        10
