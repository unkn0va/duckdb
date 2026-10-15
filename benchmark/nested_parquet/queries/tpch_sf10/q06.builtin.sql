-- TPC-H Query 6
select
        sum(l_extendedprice * l_discount) as revenue
from
        (select unnest(o_lineitems, recursive := true) from (select unnest(c_orders, recursive := true) from 'nestedcustomer.parquet'))
where
        l_shipdate >= date '1994-01-01'
        and l_shipdate < date '1994-01-01' + interval '1' year
        and l_discount between 0.06 - 0.01 and 0.06 + 0.01
        and l_quantity < 24
