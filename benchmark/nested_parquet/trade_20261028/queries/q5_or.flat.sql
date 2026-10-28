SELECT sum("legs.value") FROM read_parquet_flat('trade_B.parquet') WHERE "legs.currency" = 'AUD' OR "legs.option_type" = 'put';
