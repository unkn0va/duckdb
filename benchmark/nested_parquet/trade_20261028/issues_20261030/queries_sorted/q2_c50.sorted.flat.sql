SELECT sum("legs.value") FROM read_parquet_flat('trade_Bsorted.parquet') WHERE "legs.leg_id" < 'leg270';
