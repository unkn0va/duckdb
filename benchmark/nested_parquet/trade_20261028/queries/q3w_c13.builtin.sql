SELECT sum(e.v) FROM (SELECT unnest(c13) AS e FROM 'trade_C.parquet') WHERE e.v > 0;
