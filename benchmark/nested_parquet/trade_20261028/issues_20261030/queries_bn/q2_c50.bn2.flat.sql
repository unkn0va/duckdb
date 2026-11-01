SELECT sum("legs.value") FROM read_parquet_flat('trade_Bn2.parquet') WHERE "legs.leg_id" < 'leg270';
