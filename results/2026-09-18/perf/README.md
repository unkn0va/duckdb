# q6 perf profile — apache10, 2026-09-18, release build

`perf record -g` on `./build/release/duckdb -c "SET parquet_prenest_auto=<mode>; <q6>"`.

| | off | on | change |
|---|---|---|---|
| total cycles | 7,236M | 1,573M | 4.6x down |
| assembly (VectorOperations::Copy + memmove) | 32.7% = 2,367M | 10.2% = 160M | **14.8x down** |
| decode (SnappyDecompressor::DecompressAllTags) | 2.74% = 198M | 11.73% = 184M | **unchanged** |

Decode rises in *share* while falling in nothing absolute: total work shrank
4.6x around it. This is independent confirmation that the gain is list-assembly
copy reduction, not decode avoidance — matching `elements_decoded` staying at
6,045,075 while `elements_appended` drops to 114,160.

In the off profile, ~2/3 of the memmove time is page-fault handling
(`asm_exc_page_fault` -> `handle_mm_fault`): touching fresh pages for 6M
elements x 4 leaf columns. That cost disappears with the filter.
