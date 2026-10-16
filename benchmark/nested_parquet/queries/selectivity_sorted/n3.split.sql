SELECT avg(greatest(a, b)) FROM 'normalized/l1_0.parquet' l0 JOIN 'normalized/l1_1.parquet' l1 ON l0._sk = l1._psk0 WHERE a < 1000;
