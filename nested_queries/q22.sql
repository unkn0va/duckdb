with avg_balance as (
    select avg(c_acctbal) as avg_bal
    from customer
    where c_acctbal > 0.00
      and substring(c_phone from 1 for 2) in ('24','34','16','30','33','14','13')
)
select cntrycode, count(*) as numcust, sum(c_acctbal) as totacctbal
from (
    select substring(c_phone from 1 for 2) as cntrycode, c_acctbal
    from customer, avg_balance
    where substring(c_phone from 1 for 2) in ('24','34','16','30','33','14','13')
      and c_acctbal > avg_bal
      and len(c_orders) = 0
) as custsale
group by cntrycode
order by cntrycode
