-- TPC-H Query 6
select
        sum("r_nations-n_customers-c_orders-o_lineitems-l_extendedprice" * "r_nations-n_customers-c_orders-o_lineitems-l_discount") as revenue
from
        'normalized/nestedregion_4.parquet'
where
        "r_nations-n_customers-c_orders-o_lineitems-l_shipdate" >= date '1994-01-01'
        and "r_nations-n_customers-c_orders-o_lineitems-l_shipdate" < date '1994-01-01' + interval '1' year
        and "r_nations-n_customers-c_orders-o_lineitems-l_discount" between 0.06 - 0.01 and 0.06 + 0.01
        and "r_nations-n_customers-c_orders-o_lineitems-l_quantity" < 24
