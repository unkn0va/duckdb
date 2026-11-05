SELECT sum(c) FROM read_parquet_flat('../syn/syn_L4.parquet') WHERE c < 500000;
