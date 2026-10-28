SELECT sum(e.v) FROM (SELECT unnest(c12) AS e FROM 'trade_C.parquet') WHERE e.v < 8022;
