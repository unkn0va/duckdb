ATTACH '../fanout/fanout.duckdb' AS fw (READ_ONLY);
SELECT sum(len(legs)) FROM fw.trade_b;
