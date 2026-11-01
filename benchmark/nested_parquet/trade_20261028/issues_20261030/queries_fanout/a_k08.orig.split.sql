SELECT d.reg_scenario, count(*), sum(l.value) FROM 'pureflat/parent.parquet' p JOIN 'pureflat/legs.parquet' l ON p.sk = l.ak0
JOIN '../dims_k/dim_k8.parquet' d ON p.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
