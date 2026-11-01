ATTACH '../fanout/fanout.duckdb' AS fw (READ_ONLY);
SELECT d.reg_scenario, sum(t.n), sum(t.s) FROM (SELECT c8, count(*) AS n, sum(value) AS s FROM (SELECT p.c8, l.value FROM fw.legs l JOIN fw.parent p ON l.ak0 = p.sk) GROUP BY c8) t
JOIN fw.dim_k16 d ON t.c8 = d.reg_scenario GROUP BY d.reg_scenario ORDER BY d.reg_scenario;
