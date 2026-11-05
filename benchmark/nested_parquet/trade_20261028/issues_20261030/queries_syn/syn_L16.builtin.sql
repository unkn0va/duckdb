SELECT sum(v) FROM (SELECT unnest(c) AS v FROM '../syn/syn_L16.parquet') WHERE v < 500000;
