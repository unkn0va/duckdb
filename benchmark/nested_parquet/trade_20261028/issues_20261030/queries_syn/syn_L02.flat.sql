SELECT sum(c) FROM read_parquet_flat('../syn/syn_L2.parquet') WHERE c < 500000;
