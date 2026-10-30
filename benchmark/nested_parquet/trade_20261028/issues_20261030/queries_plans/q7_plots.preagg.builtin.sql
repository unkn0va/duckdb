SELECT d.reg_scenario, sum(t.n), sum(t.s) FROM (SELECT c8, count(*) AS n, sum(e.value) AS s FROM (SELECT c8, unnest(legs) AS e FROM 'trade_B.parquet') GROUP BY c8) t
JOIN '../dims/date_plots_flat.parquet' d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
