SELECT d.reg_scenario, sum(t.n), sum(t.s) FROM (SELECT p.c8, count(*) AS n, sum(l.value) AS s FROM 'pureflat/legs.parquet' l JOIN 'pureflat/parent.parquet' p ON l.ak0 = p.sk GROUP BY p.c8) t
JOIN '../dims/date_plots_flat.parquet' d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
