SELECT sum("legs.value") FROM read_parquet_flat('trade_B.parquet') WHERE c9 < 100050000;
