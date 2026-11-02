| check | trade_B.parquet | trade_Bn1.parquet | same |
|---|---|---|---|
| rows, elements, longest list | 100000000,349900000,5 | 100000000,349900000,5 | yes |
| hash of the other columns | 922366492150458179658388989 | 922366492150458179658388989 | yes |
| hash of the elements (value) | 922433719415460663166279874 | 922433719415460663166279874 | yes |
| row groups (count, rows of each) | 814,122880 122880 122880 122 … 2880 122880 122880 98560 | 814,122880 122880 122880 122 … 2880 122880 122880 98560 | yes |
| writer, compression | parquet-cpp-arrow version 26.0.0,SNAPPY | parquet-cpp-arrow version 26.0.0,SNAPPY | yes |

| check | trade_B.parquet | trade_Bn2.parquet | same |
|---|---|---|---|
| rows, elements, longest list | 100000000,349900000,5 | 100000000,349900000,5 | yes |
| hash of the other columns | 922366492150458179658388989 | 922366492150458179658388989 | yes |
| hash of the elements (leg_id, value) | 922342995046181507788779132 | 922342995046181507788779132 | yes |
| row groups (count, rows of each) | 814,122880 122880 122880 122 … 2880 122880 122880 98560 | 814,122880 122880 122880 122 … 2880 122880 122880 98560 | yes |
| writer, compression | parquet-cpp-arrow version 26.0.0,SNAPPY | parquet-cpp-arrow version 26.0.0,SNAPPY | yes |

