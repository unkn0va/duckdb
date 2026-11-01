ATTACH '../fanout/fanout.duckdb' AS fw (READ_ONLY);
SELECT d.reg_scenario, count(*), sum(t."legs.value") FROM read_parquet_flat('trade_B.parquet') t
JOIN fw.dim_k1 d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
