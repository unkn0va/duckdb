SELECT sum("c13.v") FROM read_parquet_flat('trade_C.parquet') WHERE "c13.v" > 0;
