SELECT avg(greatest(r.a, e.b)) FROM read_parquet_node('l1.parquet') r JOIN read_parquet_node('l1.parquet', node := 'b') e ON e._ak0 = r._sk WHERE r.a % 1000 = 0;
