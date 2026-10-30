SET disabled_optimizers = 'join_order';
SELECT sum(l.value) FROM 'pureflat/legs.parquet' l JOIN 'pureflat/parent.parquet' p ON l.ak0 = p.sk WHERE p.c9 < 10050000;
