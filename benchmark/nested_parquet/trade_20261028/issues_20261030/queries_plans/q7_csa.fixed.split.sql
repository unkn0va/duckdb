SET disabled_optimizers = 'join_order';
SELECT d.csa, count(*), sum(l.value) FROM 'pureflat/legs.parquet' l JOIN 'pureflat/parent.parquet' p ON l.ak0 = p.sk
JOIN '../dims/csa_dictionary.parquet' d ON p.c0 = d.as_of_date AND p.c1 = d.csa_hash GROUP BY d.csa ORDER BY d.csa;
