ATTACH '../fanout/fanout.duckdb' AS fw (READ_ONLY);
SELECT d.reg_scenario, count(*), sum(l.value) FROM fw.parent p JOIN fw.legs l ON p.sk = l.ak0
JOIN fw.dim_k2 d ON p.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
