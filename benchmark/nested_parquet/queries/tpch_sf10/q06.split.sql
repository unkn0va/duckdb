-- TPC-H Query 6
select
        sum("c_orders-o_lineitems-l_extendedprice" * "c_orders-o_lineitems-l_discount") as revenue
from
        'normalized/nestedcustomer_2.parquet'
where
        "c_orders-o_lineitems-l_shipdate" >= date '1994-01-01'
        and "c_orders-o_lineitems-l_shipdate" < date '1994-01-01' + interval '1' year
        and "c_orders-o_lineitems-l_discount" between 0.06 - 0.01 and 0.06 + 0.01
        and "c_orders-o_lineitems-l_quantity" < 24
