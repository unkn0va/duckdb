SELECT sum(e.value) FROM (SELECT unnest(legs) AS e FROM 'trade_B.parquet' WHERE c9 < 100050000);
