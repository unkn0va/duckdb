SET disabled_optimizers = 'join_order';
SELECT d.csa, count(*), sum(t.e.value) FROM (SELECT c0, c1, unnest(legs) AS e FROM 'trade_B.parquet') t
JOIN '../dims/csa_dictionary.parquet' d ON t.c0 = d.as_of_date AND t.c1 = d.csa_hash GROUP BY d.csa ORDER BY d.csa;
