-- TPC-H Query 10
select
        c_custkey,
        c_name,
        sum(l_extendedprice * (1 - l_discount)) as revenue,
        c_acctbal,
        n_name,
        c_address,
        c_phone,
        c_comment
from
        (select c_custkey, c_name, c_acctbal,
                     c_phone, c_address, c_comment, n_name, o_orderdate, unnest(o_lineitems, recursive := true) 
        from (select c_custkey, c_name, c_acctbal,
                     c_phone, c_address, c_comment, n_name, 
                     unnest(c_orders, recursive := true) 
              from (select n_name, unnest(n_customers, recursive := true) 
                    from (select unnest(r_nations, recursive := true) from 'nestedregion.parquet'))))
where
        o_orderdate >= date '1993-10-01'
        and o_orderdate < date '1993-10-01' + interval '3' month
        and l_returnflag = 'R'
group by
        c_custkey,
        c_name,
        c_acctbal,
        c_phone,
        n_name,
        c_address,
        c_comment
order by
        revenue desc
limit
        20
