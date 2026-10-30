SET disabled_optimizers = 'join_order';
SELECT c5, sum(e.value) FROM (SELECT c5, unnest(legs) AS e FROM 'trade_B.parquet') WHERE e.value < 507400 GROUP BY c5 ORDER BY c5;
