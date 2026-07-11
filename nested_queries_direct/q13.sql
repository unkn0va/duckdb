select c_count, count(*) as custdist
from (
    select c_custkey,
        sum(case when o.o_comment not like '%express%requests%' then 1 else 0 end) as c_count
    from (select c_custkey, unnest(c_orders) as o from '/home/layun03/data/tpch-nested/1/customer.parquet')
    group by c_custkey
) as c_orders_agg
group by c_count
order by custdist desc, c_count desc
