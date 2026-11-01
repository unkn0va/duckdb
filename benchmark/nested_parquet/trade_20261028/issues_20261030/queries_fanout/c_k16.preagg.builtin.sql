ATTACH '../fanout/fanout.duckdb' AS fw (READ_ONLY);
SELECT d.reg_scenario, sum(t.n), sum(t.s) FROM (SELECT c8, count(*) AS n, sum(e.value) AS s FROM (SELECT c8, unnest(legs) AS e FROM fw.trade_b) GROUP BY c8) t
JOIN fw.dim_k16 d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
