SET disabled_optimizers = 'join_order';
SELECT sum("legs.value") FROM read_parquet_flat('trade_B.parquet') WHERE c9 < 500050000;
