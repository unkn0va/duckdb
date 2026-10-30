SELECT d.reg_scenario, sum(t.n), sum(t.s) FROM (SELECT c8, count(*) AS n, sum("legs.value") AS s FROM read_parquet_flat('trade_B.parquet') GROUP BY c8) t
JOIN '../dims/date_plots_flat.parquet' d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
