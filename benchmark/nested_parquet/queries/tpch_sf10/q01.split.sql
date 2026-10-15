-- TPC-H Query 1
select
        "c_orders-o_lineitems-l_returnflag",
        "c_orders-o_lineitems-l_linestatus",
        sum("c_orders-o_lineitems-l_quantity") as sum_qty,
        sum("c_orders-o_lineitems-l_extendedprice") as sum_base_price,
        sum("c_orders-o_lineitems-l_extendedprice" * (1 - "c_orders-o_lineitems-l_discount")) as sum_disc_price,
        sum("c_orders-o_lineitems-l_extendedprice" * (1 - "c_orders-o_lineitems-l_discount") * (1 + "c_orders-o_lineitems-l_tax")) as sum_charge,
        avg("c_orders-o_lineitems-l_quantity") as avg_qty,
        avg("c_orders-o_lineitems-l_extendedprice") as avg_price,
        avg("c_orders-o_lineitems-l_discount") as avg_disc,
        count(*) as count_order
from
        'normalized/nestedcustomer_2.parquet'
where
        "c_orders-o_lineitems-l_shipdate" <= date '1998-12-01' - interval '90' day
group by
        "c_orders-o_lineitems-l_returnflag",
        "c_orders-o_lineitems-l_linestatus"
order by
        "c_orders-o_lineitems-l_returnflag",
        "c_orders-o_lineitems-l_linestatus"
