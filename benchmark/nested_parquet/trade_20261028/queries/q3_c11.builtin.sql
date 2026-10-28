SELECT sum(v) FROM (SELECT unnest(c11) AS v FROM 'trade_B.parquet') WHERE v < 39264604;
