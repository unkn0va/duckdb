SELECT sum("c12.v") FROM read_parquet_flat('trade_C.parquet') WHERE "c12.v" < 8022;
