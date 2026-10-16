#!/usr/bin/env python3
"""Data for experiment (B) of the selectivity benchmark (RESULTS.md): the shape of the paper's synthetic/l1.parquet -
1M rows with a BIGINT "a" and a list "b" of 10 random BIGINTs, in one row group - but with "a" ascending (a = row
number), so that a range predicate on "a" selects a contiguous range of rows and of keys. Also writes the pre-split
version, with split_selectivity_data.py.

Written with pyarrow 26.0.0 (Python 3.12) and its default writer settings (1 MB data pages, dictionary encoding that
falls back to plain, snappy), like the parquet-cpp-arrow files of the paper. To regenerate:

  python3 -m venv /tmp/pyarrow-env
  /tmp/pyarrow-env/bin/pip install pyarrow==26.0.0
  /tmp/pyarrow-env/bin/python benchmark/nested_parquet/generate_selectivity_data.py <output dir>

It writes <output dir>/l1.parquet (about 90 MB) and <output dir>/normalized/l1_0.parquet, l1_1.parquet.
"""
import os
import random
import sys

import pyarrow as pa
import pyarrow.parquet as pq

from split_selectivity_data import write_split_files

ROWS = 1_000_000
LIST_LENGTH = 10

output_dir = sys.argv[1]
os.makedirs(output_dir, exist_ok=True)

rng = random.Random(42)
a = pa.array(range(ROWS), pa.int64())
values = pa.array([rng.getrandbits(63) for _ in range(ROWS * LIST_LENGTH)], pa.int64())
offsets = pa.array(range(0, ROWS * LIST_LENGTH + 1, LIST_LENGTH), pa.int32())
table = pa.table({"a": a, "b": pa.ListArray.from_arrays(offsets, values)})

pq.write_table(table, os.path.join(output_dir, "l1.parquet"), row_group_size=ROWS)
write_split_files(table, output_dir)
