-- TPC-H Query 1
select
        "r_nations-n_customers-c_orders-o_lineitems-l_returnflag" as a,
        "r_nations-n_customers-c_orders-o_lineitems-l_linestatus" as b,
        sum("r_nations-n_customers-c_orders-o_lineitems-l_quantity") as c,
        sum("r_nations-n_customers-c_orders-o_lineitems-l_extendedprice") as d,
        sum("r_nations-n_customers-c_orders-o_lineitems-l_extendedprice" * (1 - "r_nations-n_customers-c_orders-o_lineitems-l_discount")) as e,
        sum("r_nations-n_customers-c_orders-o_lineitems-l_extendedprice" * (1 - "r_nations-n_customers-c_orders-o_lineitems-l_discount") * (1 + "r_nations-n_customers-c_orders-o_lineitems-l_tax")) as f,
        avg("r_nations-n_customers-c_orders-o_lineitems-l_quantity") as g,
        avg("r_nations-n_customers-c_orders-o_lineitems-l_extendedprice") as h,
        avg("r_nations-n_customers-c_orders-o_lineitems-l_discount") as i,
        count(*) as j
from
        'normalized/nestedregion_4.parquet'
where
        "r_nations-n_customers-c_orders-o_lineitems-l_shipdate" <= date '1998-12-01' - interval '90' day
group by
        "r_nations-n_customers-c_orders-o_lineitems-l_returnflag",
        "r_nations-n_customers-c_orders-o_lineitems-l_linestatus"
order by
        "r_nations-n_customers-c_orders-o_lineitems-l_returnflag",
        "r_nations-n_customers-c_orders-o_lineitems-l_linestatus"
