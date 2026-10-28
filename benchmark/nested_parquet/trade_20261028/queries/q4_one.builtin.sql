SELECT count(*), sum(v) FROM (SELECT unnest(c11) AS v FROM 'trade_A.parquet');
