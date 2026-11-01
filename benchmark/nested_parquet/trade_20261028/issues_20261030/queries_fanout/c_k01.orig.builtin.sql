ATTACH '../fanout/fanout.duckdb' AS fw (READ_ONLY);
SELECT d.reg_scenario, count(*), sum(t.e.value) FROM (SELECT c8, unnest(legs) AS e FROM fw.trade_b) t
JOIN fw.dim_k1 d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
