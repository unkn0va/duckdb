SELECT sum(value) FROM 'pureflat/legs.parquet' WHERE currency = 'EUR' OR currency = 'USD';
