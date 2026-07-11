with revenue0 as (
    select l.l_suppkey as supplier_no,
           sum(l.l_extendedprice * (1 - l.l_discount)) as total_revenue
    from (select unnest(o.o_lineitems) as l
          from (select unnest(c_orders) as o from '/home/layun03/data/tpch-nested/1/customer.parquet')) ls
    where l.l_shipdate >= '1996-08-01'
      and l.l_shipdate < '1996-11-01'
    group by l.l_suppkey
)
select s.s_suppkey, s.s_name, s.s_address, s.s_phone, r.total_revenue
from '/home/layun03/data/tpch-nested/1/supplier.parquet' s, revenue0 r
where s.s_suppkey = r.supplier_no
    and r.total_revenue = (select max(total_revenue) from revenue0)
order by s.s_suppkey
