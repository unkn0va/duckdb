SELECT sum("legs.value") FROM read_parquet_flat('trade_B.parquet') WHERE "legs.value" < 2000000;
