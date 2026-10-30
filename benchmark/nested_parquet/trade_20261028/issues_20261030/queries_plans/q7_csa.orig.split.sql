SELECT d.csa, count(*), sum(l.value) FROM 'pureflat/parent.parquet' p JOIN 'pureflat/legs.parquet' l ON p.sk = l.ak0
JOIN '../dims/csa_dictionary.parquet' d ON p.c0 = d.as_of_date AND p.c1 = d.csa_hash GROUP BY d.csa ORDER BY d.csa;
