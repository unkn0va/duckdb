SELECT c5, sum("legs.value") FROM read_parquet_flat('trade_B.parquet') WHERE "legs.value" < 507400 GROUP BY c5 ORDER BY c5;
