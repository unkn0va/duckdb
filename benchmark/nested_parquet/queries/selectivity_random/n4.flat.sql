SELECT avg(greatest(a, b)) FROM read_parquet_flat('l1.parquet') WHERE a % 10000 = 0;
