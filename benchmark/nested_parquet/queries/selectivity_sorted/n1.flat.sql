SELECT avg(greatest(a, b)) FROM read_parquet_flat('l1.parquet') WHERE a < 100000;
