SELECT d.csa, sum(t.n), sum(t.s) FROM (SELECT c0, c1, count(*) AS n, sum(e.value) AS s FROM (SELECT c0, c1, unnest(legs) AS e FROM 'trade_B.parquet') GROUP BY c0, c1) t
JOIN '../dims/csa_dictionary.parquet' d ON t.c0 = d.as_of_date AND t.c1 = d.csa_hash GROUP BY d.csa ORDER BY d.csa;
