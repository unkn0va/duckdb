select
    100.00 * sum(case when p.p_type like 'PROMO%'
        then l.l_extendedprice * (1 - l.l_discount) else 0 end)
    / sum(l.l_extendedprice * (1 - l.l_discount)) as promo_revenue
from (
    select unnest(ol) as l
    from (select unnest(c_orders).o_lineitems as ol from '/home/layun03/data/tpch-nested/1/customer.parquet')
) ls, '/home/layun03/data/tpch-nested/1/part.parquet' p
where ls.l.l_partkey = p.p_partkey
    and ls.l.l_shipdate >= '1995-02-01'
    and ls.l.l_shipdate < '1995-03-01'
