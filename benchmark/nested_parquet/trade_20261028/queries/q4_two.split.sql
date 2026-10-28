SELECT count(*), sum(a.c11), sum(length(b.c14)) FROM 'pureflat/c11.parquet' a JOIN 'pureflat/c14.parquet' b ON a.ak0 = b.ak0;
