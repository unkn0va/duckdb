select ps.ps_partkey, sum(ps.ps_supplycost * ps.ps_availqty) as value
from
    (select s_suppkey, s_nationkey, unnest(s_partsupps) as ps from '/home/layun03/data/tpch-nested/1/supplier.parquet') sps,
    (select unnest(r_nations) as n from '/home/layun03/data/tpch-nested/1/region.parquet') ns
where sps.s_nationkey = ns.n.n_nationkey
    and ns.n.n_name = 'ALGERIA'
group by ps.ps_partkey
having sum(ps.ps_supplycost * ps.ps_availqty) > (
    select sum(ps2.ps_supplycost * ps2.ps_availqty) * 0.0001000000
    from (select s_suppkey, s_nationkey, unnest(s_partsupps) as ps2 from '/home/layun03/data/tpch-nested/1/supplier.parquet') sps2,
         (select unnest(r_nations) as n2 from '/home/layun03/data/tpch-nested/1/region.parquet') ns2
    where sps2.s_nationkey = ns2.n2.n_nationkey
      and ns2.n2.n_name = 'ALGERIA'
)
order by value desc
