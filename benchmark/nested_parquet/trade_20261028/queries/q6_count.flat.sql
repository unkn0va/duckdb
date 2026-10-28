SELECT count(*) FROM read_parquet_flat('trade_B.parquet') WHERE "legs.value" < 507400;
