SELECT p.c5, sum(l.value) FROM 'pureflat/parent.parquet' p JOIN 'pureflat/legs.parquet' l ON p.sk = l.ak0 WHERE l.value < 507400 GROUP BY p.c5 ORDER BY p.c5;
