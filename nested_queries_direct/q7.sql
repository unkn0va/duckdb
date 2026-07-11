select
  supp_nation,
  cust_nation,
  l_year,
  sum(volume) as revenue
from (
  select
    n1.n.n_name as supp_nation,
    n2.n.n_name as cust_nation,
    extract(year from l.l_shipdate) as l_year,
    l.l_extendedprice * (1 - l.l_discount) as volume
  from
    (
      select 
        c_nationkey,
        unnest(o.o_lineitems) as l
      from (
        select 
          c_nationkey,
          unnest(c_orders) as o
        from 
          '/home/layun03/data/tpch-nested/1/customer.parquet'
      ) os
    ) ls,
    '/home/layun03/data/tpch-nested/1/supplier.parquet' s,
    (
      select unnest(r_nations) as n
      from '/home/layun03/data/tpch-nested/1/region.parquet'
    ) n1,
    (
      select unnest(r_nations) as n
      from '/home/layun03/data/tpch-nested/1/region.parquet'
    ) n2
  where
    s_suppkey = l.l_suppkey
    and s_nationkey = n1.n.n_nationkey
    and c_nationkey = n2.n.n_nationkey
    and (
      (n1.n.n_name = 'FRANCE' and n2.n.n_name = 'GERMANY')
      or (n1.n.n_name = 'GERMANY' and n2.n.n_name = 'FRANCE')
    )
    and l.l_shipdate between '1995-01-01' and '1996-12-31'
  ) as shipping
group by
  supp_nation,
  cust_nation,
  l_year
order by
  supp_nation,
  cust_nation,
  l_year;