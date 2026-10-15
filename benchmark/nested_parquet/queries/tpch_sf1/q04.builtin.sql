-- TPC-H Query 4
select
        o_orderpriority,
        count(*) as order_count
from
        (
                select distinct o_orderkey, o_orderpriority
                from (select o_orderkey, o_orderpriority, o_orderdate, unnest(o_lineitems, recursive := true) from (select unnest(c_orders, recursive := true) from (select unnest(n_customers, recursive := true) from (select unnest(r_nations, recursive := true) from 'nestedregion.parquet')))) l
                where o_orderdate >= date '1993-07-01'
                and o_orderdate < date '1993-07-01' + interval '3' month
                and l_commitdate < l_receiptdate
        )
group by
        o_orderpriority
order by
        o_orderpriority
