SELECT avg(greatest(a, b)) FROM (SELECT a, unnest(b) AS b FROM 'l1.parquet' WHERE a < 1);
