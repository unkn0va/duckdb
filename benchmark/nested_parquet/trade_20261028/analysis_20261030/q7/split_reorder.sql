SET disabled_optimizers = 'join_order';
SELECT d.reg_scenario, count(*), sum(l.value) FROM 'pureflat/legs.parquet' l JOIN 'pureflat/parent.parquet' p ON l.ak0 = p.sk
JOIN '../dims/date_plots_flat.parquet' d ON p.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
