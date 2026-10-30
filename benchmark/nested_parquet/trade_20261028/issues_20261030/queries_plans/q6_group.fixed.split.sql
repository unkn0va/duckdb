SET disabled_optimizers = 'join_order';
SELECT p.c5, sum(l.value) FROM 'pureflat/legs.parquet' l JOIN 'pureflat/parent.parquet' p ON l.ak0 = p.sk WHERE l.value < 507400 GROUP BY p.c5 ORDER BY p.c5;
