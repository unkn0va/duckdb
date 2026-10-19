#!/usr/bin/env python3
"""Split a nested file of the shape of the paper's synthetic/l1.parquet (a BIGINT "a" and a list "b" of BIGINTs) into
pre-split files with stored keys, laid out like the paper's synthetic/normalized/l1_0.parquet and l1_1.parquet:

- normalized/l1_0.parquet: a, _sk (INT32, 1-based row number), one row group
- normalized/l1_1.parquet: b, _psk0 (INT32, the _sk of the parent row), _sk (INT32, 1-based element number), row groups
  of 1M rows

The paper's pre-split files hold other random values than its l1.parquet, so the split variant of the selectivity
benchmark is measured on files split from the nested one - with the same values, its results are checked as well.

Written with pyarrow 26.0.0 (Python 3.12) and its default writer settings. To regenerate:

  python3 -m venv /tmp/pyarrow-env
  /tmp/pyarrow-env/bin/pip install pyarrow==26.0.0
  /tmp/pyarrow-env/bin/python benchmark/nested_parquet/split_selectivity_data.py <l1.parquet> <output dir>

It writes <output dir>/normalized/l1_0.parquet and l1_1.parquet.
"""
import os
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROW_GROUP_ROWS = 1_000_000


def write_split_files(table, output_dir):
    os.makedirs(os.path.join(output_dir, "normalized"), exist_ok=True)
    rows = table.num_rows
    lists = table.column("b").combine_chunks()
    elements = lists.flatten()
    parent_sk = pc.add(pc.list_parent_indices(lists), 1).cast(pa.int32())
    pq.write_table(
        pa.table({"a": table.column("a"), "_sk": pa.array(range(1, rows + 1), pa.int32())}),
        os.path.join(output_dir, "normalized", "l1_0.parquet"),
        row_group_size=ROW_GROUP_ROWS,
    )
    pq.write_table(
        pa.table({"b": elements, "_psk0": parent_sk, "_sk": pa.array(range(1, len(elements) + 1), pa.int32())}),
        os.path.join(output_dir, "normalized", "l1_1.parquet"),
        row_group_size=ROW_GROUP_ROWS,
    )


if __name__ == "__main__":
    write_split_files(pq.read_table(sys.argv[1]), sys.argv[2])
