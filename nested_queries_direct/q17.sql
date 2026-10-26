with all_lineitems as (
    select
        l.l_partkey as l_partkey,
        l.l_quantity as l_quantity,
        l.l_extendedprice as l_extendedprice
    from (select unnest(o.o_lineitems) as l
          from (select unnest(c_orders) as o from '/home/layun03/data/tpch-nested/1/customer.parquet')) ls
),
matching_parts as (
    select p_partkey from '/home/layun03/data/tpch-nested/1/part.parquet'
    where p_brand = 'Brand#42' and p_container = 'LG BAG'
),
lineitem_for_parts as (
    select * from all_lineitems
    where l_partkey in (select p_partkey from matching_parts)
),
part_avg_qty as (
    select l_partkey, 0.2 * avg(l_quantity) as avg_qty_threshold
    from lineitem_for_parts group by l_partkey
)
select sum(lf.l_extendedprice) / 7.0 as avg_yearly
from lineitem_for_parts lf, part_avg_qty paq
where lf.l_partkey = paq.l_partkey
    and lf.l_quantity < paq.avg_qty_threshold
