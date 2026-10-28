SELECT sum(v) FROM (SELECT unnest(c13) AS v FROM 'trade_B.parquet') WHERE v > 0;
