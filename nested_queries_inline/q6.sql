-- TPCH-Q6 (inline form: inner list extracted on the unnest so nested projection pushdown reaches leaves)
select
  sum(l.l_extendedprice * l.l_discount) as revenue
from
  (
    select unnest(ol) as l
    from (
      select unnest(c_orders).o_lineitems as ol
      from '/home/layun03/data/tpch-nested/1/customer.parquet'
    )
  )
where
  l.l_shipdate >= '1994-01-01'
  and l.l_shipdate < '1995-01-01'
  and l.l_discount between 0.05 and 0.07
  and l.l_quantity < 24;
