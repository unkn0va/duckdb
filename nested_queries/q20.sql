with lineitem_agg as (
    select
        l.l_partkey as l_partkey,
        l.l_suppkey as l_suppkey,
        sum(l.l_quantity) as total_qty
    from (select unnest(o.o_lineitems) as l
          from (select unnest(c_orders) as o from customer)) ls
    where l.l_shipdate >= '1993-01-01' and l.l_shipdate < '1994-01-01'
    group by l.l_partkey, l.l_suppkey
)
select s.s_name, s.s_address
from supplier s,
     (select unnest(r_nations) as n from region where r_name = 'AFRICA') ns
where s.s_suppkey in (
    select sps.s_suppkey
    from (select s_suppkey, unnest(s_partsupps) as ps from supplier) sps
        join part p on p.p_partkey = sps.ps.ps_partkey
        join lineitem_agg la on la.l_partkey = sps.ps.ps_partkey
            and la.l_suppkey = sps.s_suppkey
    where p.p_name like 'blanched%'
        and sps.ps.ps_availqty > 0.5 * la.total_qty
)
    and s.s_nationkey = ns.n.n_nationkey
    and ns.n.n_name = 'KENYA'
order by s.s_name
