select
  o_year,
  sum(case
    when nation = 'BRAZIL'
    then volume
    else 0
  end) / sum(volume) as mkt_share
from (
  select
    extract(year from o_orderdate) as o_year,
    l.l_extendedprice * (1 - l.l_discount) as volume,
    n2.n.n_name as nation
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
            from 
                customer
        ) os
    ) ls,
    supplier s,
    part p,
    (
        select 
            r_name,
            unnest(r_nations) as n
        from region r
    ) n1,
    (
        select unnest(r_nations) as n
        from region
    ) n2
  where
    p_partkey = l.l_partkey
    and s_suppkey = l.l_suppkey
    and c_nationkey = n1.n.n_nationkey
    and r_name = 'AMERICA'
    and s.s_nationkey = n2.n.n_nationkey
    and o_orderdate between '1995-01-01' and '1996-12-31'
    and p_type = 'ECONOMY ANODIZED STEEL'
  ) as all_nations
group by
  o_year
order by
  o_year;