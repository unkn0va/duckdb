SELECT sum("c11.v") FROM read_parquet_flat('trade_C.parquet') WHERE "c11.v" < 39264604;
