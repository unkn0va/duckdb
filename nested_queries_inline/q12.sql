-- TPCH-Q12 (clean-inline form: extract each needed o-field inline via unnest(c_orders).field —
-- aligned unnests — so the inner UNNEST input (ol) is a colref and leaf pushdown works, while
-- avoiding the bound-o form that triggers a StructStats core crash)
select
    l.l_shipmode,
    sum(case when o_orderpriority = '1-URGENT' or o_orderpriority = '2-HIGH' then 1 else 0 end) as high_line_count,
    sum(case when o_orderpriority <> '1-URGENT' and o_orderpriority <> '2-HIGH' then 1 else 0 end) as low_line_count
from (
    select o_orderpriority, unnest(ol) as l
    from (
        select unnest(c_orders).o_orderpriority as o_orderpriority,
               unnest(c_orders).o_lineitems as ol
        from '/home/layun03/data/tpch-nested/1/customer.parquet'
    )
)
where l.l_shipmode in ('FOB', 'SHIP')
    and l.l_commitdate < l.l_receiptdate
    and l.l_shipdate < l.l_commitdate
    and l.l_receiptdate >= '1995-01-01'
    and l.l_receiptdate < '1996-01-01'
group by l.l_shipmode
order by l.l_shipmode
