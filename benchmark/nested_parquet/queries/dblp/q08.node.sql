select a.author, p.year, count(p.title) from read_parquet_node('dblp.parquet') p join read_parquet_node('dblp.parquet', node := 'author') a on p._sk = a._ak0
where p.title like '%database%' and p.title like '%text%' and p.title like '%mining%' group by a.author, p.year
