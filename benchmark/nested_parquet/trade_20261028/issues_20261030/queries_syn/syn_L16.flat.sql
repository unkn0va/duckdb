SELECT sum(c) FROM read_parquet_flat('../syn/syn_L16.parquet') WHERE c < 500000;
