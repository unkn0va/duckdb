| check | trade_B.parquet | trade_Bsorted.parquet | same |
|---|---|---|---|
| rows, elements, longest list | 100000000,349900000,5 | 100000000,349900000,5 | yes |
| hash of every row, in any order | 920985373142874621391743670 | 920985373142874621391743670 | yes |
| row groups (count, rows of each) | 814,122880 122880 122880 122 … 2880 122880 122880 98560 | 814,122880 122880 122880 122 … 2880 122880 122880 98560 | yes |
| writer, compression | parquet-cpp-arrow version 26.0.0,SNAPPY | parquet-cpp-arrow version 26.0.0,SNAPPY | yes |
| positional hash (differs when reordered) | 922380305299001090579788131 | 922289444419298589822121647 | differs (expected) |
