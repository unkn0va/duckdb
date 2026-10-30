SET disabled_optimizers = 'statistics_propagation';
SELECT count(leg_id), count(value) FROM 'pureflat/legs.parquet';
