SELECT sum(value) FROM 'pureflat/legs.parquet' WHERE currency = 'AUD' OR option_type = 'put';
