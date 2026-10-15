select a.author as a, count(p.title) as b from read_parquet_node('dblp.parquet') p join read_parquet_node('dblp.parquet', node := 'author') a on p._sk = a._ak0 group by a.author
