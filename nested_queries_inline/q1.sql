-- TPCH-Q1 (inline form: inner list extracted on the unnest so the inner UNNEST's input is a colref,
-- which lets nested projection pushdown reach the leaf l_* fields)
select
  l.l_returnflag,
  l.l_linestatus,
  sum(l.l_quantity) as sum_qty,
  sum(l.l_extendedprice) as sum_base_price,
  sum(l.l_extendedprice * (1 - l.l_discount)) as sum_disc_price,
  sum(l.l_extendedprice * (1 - l.l_discount) * (1 + l.l_tax)) as sum_charge,
  avg(l.l_quantity) as avg_qty,
  avg(l.l_extendedprice) as avg_price,
  avg(l.l_discount) as avg_disc,
  count(*) as count_order
from (
  select unnest(ol) as l
  from (
    select unnest(c_orders).o_lineitems as ol
    from '/home/layun03/data/tpch-nested/1/customer.parquet'
  )
)
where
  l.l_shipdate <= '1998-09-02'
group by
  l.l_returnflag,
  l.l_linestatus
order by
  l.l_returnflag,
  l.l_linestatus;
