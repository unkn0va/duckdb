ATTACH '../fanout/fanout.duckdb' AS fw (READ_ONLY);
SELECT sum(e.value) FROM (SELECT unnest(legs) AS e FROM fw.trade_b) WHERE e.leg_id < 'leg270';
