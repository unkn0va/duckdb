-- TPCH-Q1
-- Q1 - Pricing Summary Report Query
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
  select unnest(o.o_lineitems) as l
  from (
    select unnest(c_orders) as o
    from customer
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