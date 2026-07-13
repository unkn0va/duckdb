--# TPCH-Q3
--# Q3 - Shipping Priority Query
select
  o_orderkey,
  sum(l.l_extendedprice * (1 - l.l_discount)) as revenue,
  o_orderdate,
  o_shippriority
from (
  select 
    unnest(o.o_lineitems) as l,
    o.o_orderkey o_orderkey,
    o.o_orderdate o_orderdate,
    o.o_shippriority o_shippriority,
    c_mktsegment
  from (
    select 
      unnest(c_orders) as o,
      c_mktsegment
    from customer
    where c_mktsegment = 'BUILDING'
  ) 
  where o.o_orderdate < '1995-03-15'
) ls
where l.l_shipdate > '1995-03-15'
group by
  o_orderkey,
  o_orderdate,
  o_shippriority
order by
  revenue desc,
  o_orderdate
limit 10;