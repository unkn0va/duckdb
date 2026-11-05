SELECT sum(c) FROM read_parquet_flat('../syn/syn_L8.parquet') WHERE c < 500000;
