select s.s_name, count(*) as numwait
from supplier s,
(
    select l1.l_suppkey as l1_suppkey, o_orderkey
    from (
        select o.o_orderkey as o_orderkey, o.o_orderstatus as o_orderstatus,
               unnest(o.o_lineitems) as l1
        from (select unnest(c_orders) as o from customer)
        where o.o_orderstatus = 'F'
    ) ol1
    where l1.l_receiptdate > l1.l_commitdate
) waiting,
(select unnest(r_nations) as n from region) ns
where s.s_suppkey = waiting.l1_suppkey
    and s.s_nationkey = ns.n.n_nationkey
    and ns.n.n_name = 'ARGENTINA'
group by s.s_name
order by numwait desc, s.s_name
limit 100
