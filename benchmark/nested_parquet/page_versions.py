#!/usr/bin/env python3
"""The version of the data pages of the Parquet files under the given directories (RESULTS.md, "Page format of the
paper's files").

For every column chunk of every row group, the type of its first data page is read from the page header at the
chunk's data_page_offset: the first field of the Thrift PageHeader (compact protocol), 0 = DATA_PAGE (v1),
3 = DATA_PAGE_V2. Printed per file: the writer (created_by) and how many column chunks start with which page type.

Needs pyarrow (for the footer; tested with 26.0.0).

Usage: page_versions.py <dir> [<dir> ...]
"""
import collections
import os
import sys

import pyarrow.parquet as pq

PAGE_TYPES = {0: "v1", 1: "index", 2: "dictionary", 3: "v2"}


def read_varint(f):
    shift = result = 0
    while True:
        byte = f.read(1)[0]
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result
        shift += 7


def first_page_type(f, offset):
    # field 1 "type" of the PageHeader is an i32: field header 0x15, then a zigzag varint
    f.seek(offset)
    header = f.read(1)[0]
    if header != 0x15:
        return f"? (field header {header:#x})"
    value = read_varint(f)
    return PAGE_TYPES.get((value >> 1) ^ -(value & 1), f"type {value}")


for directory in sys.argv[1:]:
    for root, _, files in sorted(os.walk(directory)):
        for name in sorted(files):
            if not name.endswith(".parquet"):
                continue
            path = os.path.join(root, name)
            metadata = pq.ParquetFile(path).metadata
            counts = collections.Counter()
            with open(path, "rb") as f:
                for rg in range(metadata.num_row_groups):
                    group = metadata.row_group(rg)
                    for c in range(group.num_columns):
                        counts[first_page_type(f, group.column(c).data_page_offset)] += 1
            print(f"{os.path.relpath(path, directory)}\t{metadata.created_by}\t{dict(counts)}")
