select
  c_custkey,
  c_name,
  sum(l.l_extendedprice * (1 - l.l_discount)) as revenue,
  c_acctbal,
  n.n_name,
  c_address,
  c_phone,
  c_comment
from
  (
    select 
      c_custkey,
      c_name,
      c_acctbal,
      c_address,
      c_phone,
      c_comment,
      c_nationkey,
      o.o_orderdate o_orderdate,
      unnest(o.o_lineitems) as l
    from (
      select 
        c_custkey,
        c_name,
        c_acctbal,
        c_address,
        c_phone,
        c_comment,
        c_nationkey,
        unnest(c_orders) as o
      from 
        customer
    ) os
  ) ls,
  (
      select 
          unnest(r_nations) as n
      from region
  ) ns
where
  o_orderdate >= '1993-10-01'
  and o_orderdate < '1994-01-01'
  and l.l_returnflag = 'R'
  and c_nationkey = n.n_nationkey
group by
  c_custkey,
  c_name,
  c_acctbal,
  c_phone,
  n.n_name,
  c_address,
  c_comment
order by
  revenue desc
limit 20;