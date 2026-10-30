SET disabled_optimizers = 'join_order';
SELECT sum(e.value) FROM (SELECT unnest(legs) AS e FROM 'trade_B.parquet' WHERE c9 < 500050000);
