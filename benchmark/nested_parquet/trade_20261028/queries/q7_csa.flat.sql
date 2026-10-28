SELECT d.csa, count(*), sum(t."legs.value") FROM read_parquet_flat('trade_B.parquet') t
JOIN '../dims/csa_dictionary.parquet' d ON t.c0 = d.as_of_date AND t.c1 = d.csa_hash GROUP BY d.csa ORDER BY d.csa;
