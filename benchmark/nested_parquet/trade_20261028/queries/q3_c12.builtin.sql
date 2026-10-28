SELECT sum(v) FROM (SELECT unnest(c12) AS v FROM 'trade_B.parquet') WHERE v < 8022;
