-- TPC-H Query 12
select
       "c_orders-o_lineitems-l_shipmode",
        sum(case
                when"c_orders-o_orderpriority" = '1-URGENT'
                        or"c_orders-o_orderpriority" = '2-HIGH'
                        then 1
                else 0
        end) as high_line_count,
        sum(case
                when"c_orders-o_orderpriority" <> '1-URGENT'
                        and"c_orders-o_orderpriority" <> '2-HIGH'
                        then 1
                else 0
        end) as low_line_count
from
        'normalized/nestedcustomer_1.parquet' o
                inner join 'normalized/nestedcustomer_2.parquet' l on o._sk = l._psk1
where
        "c_orders-o_lineitems-l_shipmode" in ('MAIL', 'SHIP')
        and"c_orders-o_lineitems-l_commitdate" <"c_orders-o_lineitems-l_receiptdate"
        and"c_orders-o_lineitems-l_shipdate" <"c_orders-o_lineitems-l_commitdate"
        and"c_orders-o_lineitems-l_receiptdate" >= date '1994-01-01'
        and"c_orders-o_lineitems-l_receiptdate" < date '1994-01-01' + interval '1' year
group by
       "c_orders-o_lineitems-l_shipmode"
order by
       "c_orders-o_lineitems-l_shipmode";
