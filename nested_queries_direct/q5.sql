select
  n.n_name,
  sum(l.l_extendedprice * (1 - l.l_discount)) as revenue
from
  (
    select 
      c_nationkey,
      o.o_orderdate o_orderdate,
      unnest(o.o_lineitems) as l
    from (
      select 
        c_nationkey,
        unnest(c_orders) as o
      from '/home/layun03/data/tpch-nested/1/customer.parquet'
    )
  ) ls, 
  '/home/layun03/data/tpch-nested/1/supplier.parquet' s,
  ( 
    select 
      r_name,
      unnest(r_nations) as n
    from '/home/layun03/data/tpch-nested/1/region.parquet'
  ) ns

where
  l.l_suppkey = s.s_suppkey
  and c_nationkey = s_nationkey
  and s_nationkey = n.n_nationkey
  and r_name = 'ASIA'
  and o_orderdate >= '1994-01-01'
  and o_orderdate < '1995-01-01'
group by
  n.n_name
order by
  revenue desc;