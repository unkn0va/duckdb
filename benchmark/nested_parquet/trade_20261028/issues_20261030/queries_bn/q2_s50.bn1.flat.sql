SELECT sum("legs.value") FROM read_parquet_flat('trade_Bn1.parquet') WHERE "legs.value" < 507400;
