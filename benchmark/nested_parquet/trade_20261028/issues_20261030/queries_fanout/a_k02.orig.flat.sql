SELECT d.reg_scenario, count(*), sum(t."legs.value") FROM read_parquet_flat('trade_B.parquet') t
JOIN '../dims_k/dim_k2.parquet' d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
