SELECT sum(c12) FROM read_parquet_flat('trade_B.parquet') WHERE c12 < 8022;
