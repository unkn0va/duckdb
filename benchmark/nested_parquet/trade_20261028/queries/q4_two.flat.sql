SELECT count(*), sum(c11), sum(length(c14)) FROM read_parquet_flat('trade_A.parquet');
