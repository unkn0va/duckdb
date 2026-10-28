SELECT sum(c13) FROM read_parquet_flat('trade_B.parquet') WHERE c13 > 0;
