SELECT sum("legs.value") FROM read_parquet_flat('trade_B.parquet') WHERE "legs.currency" = 'EUR' OR "legs.currency" = 'USD' OR "legs.currency" = 'GBP';
