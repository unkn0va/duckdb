with supplier_parts as (
    select s_suppkey, s_acctbal, s_name, s_address, s_phone, s_comment,
           s_nationkey,
           ps.ps_partkey as ps_partkey,
           ps.ps_supplycost as ps_supplycost
    from (select s_suppkey, s_acctbal, s_name, s_address, s_phone, s_comment,
                 s_nationkey, unnest(s_partsupps) as ps from supplier) sps
),
nations_asia as (
    select n.n_nationkey as n_nationkey, n.n_name as n_name
    from (select r_name, unnest(r_nations) as n from region) rn
    where r_name = 'ASIA'
),
min_cost as (
    select sp2.ps_partkey, min(sp2.ps_supplycost) as min_supplycost
    from supplier_parts sp2
    join nations_asia na2 on sp2.s_nationkey = na2.n_nationkey
    group by sp2.ps_partkey
)
select
    sp.s_acctbal, sp.s_name, na.n_name,
    p.p_partkey, p.p_mfgr,
    sp.s_address, sp.s_phone, sp.s_comment
from
    supplier_parts sp,
    part p,
    nations_asia na,
    min_cost mc
where
    p.p_partkey = sp.ps_partkey
    and p.p_size = 48
    and p.p_type like '%TIN'
    and sp.s_nationkey = na.n_nationkey
    and sp.ps_partkey = mc.ps_partkey
    and sp.ps_supplycost = mc.min_supplycost
order by sp.s_acctbal desc, na.n_name, sp.s_name, p.p_partkey
limit 100
