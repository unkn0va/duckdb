SELECT count("legs.leg_id"), count("legs.value") FROM read_parquet_flat('trade_B.parquet');
