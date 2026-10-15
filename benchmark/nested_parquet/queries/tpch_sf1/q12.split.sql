-- TPC-H Query 12
select
       "r_nations-n_customers-c_orders-o_lineitems-l_shipmode",
        sum(case
                when"r_nations-n_customers-c_orders-o_orderpriority" = '1-URGENT'
                        or"r_nations-n_customers-c_orders-o_orderpriority" = '2-HIGH'
                        then 1
                else 0
        end) as high_line_count,
        sum(case
                when"r_nations-n_customers-c_orders-o_orderpriority" <> '1-URGENT'
                        and"r_nations-n_customers-c_orders-o_orderpriority" <> '2-HIGH'
                        then 1
                else 0
        end) as low_line_count
from
        'normalized/nestedregion_3.parquet' o
                inner join 'normalized/nestedregion_4.parquet' l on o._sk = l._psk3
where
        "r_nations-n_customers-c_orders-o_lineitems-l_shipmode" in ('MAIL', 'SHIP')
        and"r_nations-n_customers-c_orders-o_lineitems-l_commitdate" <"r_nations-n_customers-c_orders-o_lineitems-l_receiptdate"
        and"r_nations-n_customers-c_orders-o_lineitems-l_shipdate" <"r_nations-n_customers-c_orders-o_lineitems-l_commitdate"
        and"r_nations-n_customers-c_orders-o_lineitems-l_receiptdate" >= date '1994-01-01'
        and"r_nations-n_customers-c_orders-o_lineitems-l_receiptdate" < date '1994-01-01' + interval '1' year
group by
       "r_nations-n_customers-c_orders-o_lineitems-l_shipmode"
order by
       "r_nations-n_customers-c_orders-o_lineitems-l_shipmode";
