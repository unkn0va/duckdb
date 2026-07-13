select o_orderpriority, count(distinct o_orderkey) as order_count
from (
    select o.o_orderpriority as o_orderpriority,
           o.o_orderkey as o_orderkey,
           unnest(o.o_lineitems) as l
    from (select unnest(c_orders) as o from customer)
    where o.o_orderdate >= '1995-04-01'
      and o.o_orderdate < '1995-07-01'
)
where l.l_commitdate < l.l_receiptdate
group by o_orderpriority
order by o_orderpriority
