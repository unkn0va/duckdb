ATTACH '../fanout/fanout.duckdb' AS fw (READ_ONLY);
SELECT count(*), count(*) FROM (SELECT unnest(legs) AS e FROM fw.trade_b);
