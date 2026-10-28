SELECT sum(e.v) FROM (SELECT unnest(c11) AS e FROM 'trade_C.parquet') WHERE e.v < 39264604;
