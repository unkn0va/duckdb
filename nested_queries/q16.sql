select p.p_brand, p.p_type, p.p_size,
       count(distinct sps.s_suppkey) as supplier_cnt
from (select s_suppkey, s_comment, unnest(s_partsupps) as ps from supplier) sps, part p
where p.p_partkey = sps.ps.ps_partkey
    and p.p_brand <> 'Brand#14'
    and p.p_type not like 'SMALL PLATED%'
    and p.p_size in (14, 6, 5, 31, 49, 15, 41, 47)
    and sps.s_suppkey not in (
        select s.s_suppkey from supplier s
        where s.s_comment like '%Customer%Complaints%'
    )
group by p.p_brand, p.p_type, p.p_size
order by supplier_cnt desc, p.p_brand, p.p_type, p.p_size
