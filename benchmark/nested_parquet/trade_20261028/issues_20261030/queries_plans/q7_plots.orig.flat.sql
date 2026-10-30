SELECT d.reg_scenario, count(*), sum(t."legs.value") FROM read_parquet_flat('trade_B.parquet') t
JOIN '../dims/date_plots_flat.parquet' d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
