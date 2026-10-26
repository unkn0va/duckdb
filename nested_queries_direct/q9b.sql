select
  nation,
  o_year,
  sum(amount) as sum_profit
from (
  select
    n.n_name as nation,
    extract(year from o_orderdate) as o_year,
    l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
  from 
    (
      select 
        o.o_orderdate o_orderdate,
        unnest(o.o_lineitems) as l
      from (
        select 
          unnest(c_orders) as o
        from 
        '/home/layun03/data/tpch-nested/1/customer.parquet'
      ) os
    ) ls,
    (
      select
        s_suppkey,
        s_nationkey,
        unnest(s_partsupps) as ps
      from '/home/layun03/data/tpch-nested/1/supplier.parquet'
    ) pss,
    (
      select *
      from '/home/layun03/data/tpch-nested/1/part.parquet'
      where p_name like '%green%'
    ) p,
    (
      select 
        unnest(r_nations) as n
      from '/home/layun03/data/tpch-nested/1/region.parquet'
    ) ns
  where
    s_suppkey = l.l_suppkey
    and ps.ps_partkey = l.l_partkey
    and p_partkey = l.l_partkey
    and s_nationkey = n.n_nationkey
) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
