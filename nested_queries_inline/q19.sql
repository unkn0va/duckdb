select sum(l.l_extendedprice * (1 - l.l_discount)) as revenue
from (
    select unnest(ol) as l
    from (select unnest(c_orders).o_lineitems as ol from '/home/layun03/data/tpch-nested/1/customer.parquet')
) ls, '/home/layun03/data/tpch-nested/1/part.parquet' p
where (
    p.p_partkey = ls.l.l_partkey
    and p.p_brand = 'Brand#21'
    and p.p_container in ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')
    and ls.l.l_quantity >= 8 and ls.l.l_quantity <= 18
    and p.p_size between 1 and 5
    and ls.l.l_shipmode in ('AIR', 'AIR REG')
    and ls.l.l_shipinstruct = 'DELIVER IN PERSON'
) or (
    p.p_partkey = ls.l.l_partkey
    and p.p_brand = 'Brand#13'
    and p.p_container in ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')
    and ls.l.l_quantity >= 20 and ls.l.l_quantity <= 30
    and p.p_size between 1 and 10
    and ls.l.l_shipmode in ('AIR', 'AIR REG')
    and ls.l.l_shipinstruct = 'DELIVER IN PERSON'
) or (
    p.p_partkey = ls.l.l_partkey
    and p.p_brand = 'Brand#52'
    and p.p_container in ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')
    and ls.l.l_quantity >= 30 and ls.l.l_quantity <= 40
    and p.p_size between 1 and 15
    and ls.l.l_shipmode in ('AIR', 'AIR REG')
    and ls.l.l_shipinstruct = 'DELIVER IN PERSON'
)
