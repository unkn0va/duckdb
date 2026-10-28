SELECT sum(value) FROM 'pureflat/legs.parquet' WHERE value % 100 < 90;
