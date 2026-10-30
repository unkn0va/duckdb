SELECT count(*), count(*) FROM (SELECT unnest(legs) AS e FROM 'trade_B.parquet');
