SELECT count(*), sum(a.v), sum(length(b.s))
FROM (SELECT file_row_number AS rn, unnest(c11) AS v FROM read_parquet('trade_A.parquet', file_row_number = true)) a
JOIN (SELECT file_row_number AS rn, unnest(c14) AS s FROM read_parquet('trade_A.parquet', file_row_number = true)) b ON a.rn = b.rn;
