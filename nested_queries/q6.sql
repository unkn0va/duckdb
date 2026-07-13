select
  sum(l.l_extendedprice * l.l_discount) as revenue
from
  (
    select 
      unnest(o.o_lineitems) as l
    from (
      select 
        unnest(c_orders) as o
      from 
        customer
    ) os
  ) ls
where
  l.l_shipdate >= '1994-01-01'
  and l.l_shipdate < '1995-01-01'
  and l.l_discount between 0.05 and 0.07
  and l.l_quantity < 24;