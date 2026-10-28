SELECT sum(c11) FROM read_parquet_flat('trade_B.parquet') WHERE c11 < 39264604;
