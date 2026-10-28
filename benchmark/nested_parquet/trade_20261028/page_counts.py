#!/usr/bin/env python3
"""Row groups and pages of Parquet files: per file its size, row groups and rows, per column the number of data pages
per row group (min / average / max), the dictionary pages and the data page version.

The pages are counted by walking the page headers of every column chunk (Thrift compact protocol): the footer has no
page counts, and pyarrow 26 writes no page index by default.

Usage: page_counts.py <file or folder> [...]
"""
import collections
import os
import sys

import pyarrow.parquet as pq

PAGE_TYPES = {0: "v1", 1: "index", 2: "dictionary", 3: "v2"}


class Reader:
    def __init__(self, f):
        self.f = f

    def byte(self):
        return self.f.read(1)[0]

    def varint(self):
        shift = result = 0
        while True:
            byte = self.byte()
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result
            shift += 7

    def zigzag(self):
        value = self.varint()
        return (value >> 1) ^ -(value & 1)

    def skip(self, kind):
        if kind in (1, 2):  # booleans are in the field header
            return
        if kind == 3:
            self.f.read(1)
        elif kind in (4, 5, 6):
            self.varint()
        elif kind == 7:
            self.f.read(8)
        elif kind == 8:
            self.f.read(self.varint())
        elif kind in (9, 10):
            header = self.byte()
            size = header >> 4 if header >> 4 != 15 else self.varint()
            for _ in range(size):
                self.skip(header & 0x0F)
        elif kind == 11:
            size = self.varint()
            if size:
                types = self.byte()
                for _ in range(size):
                    self.skip(types >> 4)
                    self.skip(types & 0x0F)
        elif kind == 12:
            self.struct()
        else:
            raise ValueError(f"unknown Thrift type {kind}")

    def struct(self, wanted=()):
        """The i32 fields of a struct that are in wanted, by field id; the other fields are skipped."""
        values, last = {}, 0
        while True:
            header = self.byte()
            if header == 0:
                return values
            kind = header & 0x0F
            last = last + (header >> 4) if header >> 4 else self.zigzag()
            if last in wanted and kind == 5:
                values[last] = self.zigzag()
            else:
                self.skip(kind)


def chunk_pages(f, column):
    """Counter of the page types of a column chunk."""
    start = column.data_page_offset
    if column.has_dictionary_page and column.dictionary_page_offset:
        start = min(start, column.dictionary_page_offset)
    end = start + column.total_compressed_size
    reader, counts, position = Reader(f), collections.Counter(), start
    while position < end:
        f.seek(position)
        header = reader.struct(wanted=(1, 3))
        counts[PAGE_TYPES.get(header[1], f"type {header[1]}")] += 1
        position = f.tell() + header[3]
    return counts


def report(path):
    metadata = pq.ParquetFile(path).metadata
    groups = metadata.num_row_groups
    print(
        f"{path}: {os.path.getsize(path) / 1e6:.1f} MB, {metadata.num_rows} rows, {groups} row groups "
        f"(largest {max(metadata.row_group(g).num_rows for g in range(groups)) if groups else 0} rows)"
    )
    per_column = collections.defaultdict(list)
    with open(path, "rb") as f:
        for g in range(groups):
            group = metadata.row_group(g)
            for c in range(group.num_columns):
                column = group.column(c)
                per_column[column.path_in_schema].append(chunk_pages(f, column))
    print(f"  {'column':<28} {'data pages per row group (min/avg/max)':>40} {'total':>8} {'dict pages':>10}  version")
    for name, chunks in per_column.items():
        data = [sum(n for t, n in counts.items() if t in ("v1", "v2")) for counts in chunks]
        versions = sorted({t for counts in chunks for t in counts if t in ("v1", "v2")})
        dictionary = sum(counts["dictionary"] for counts in chunks)
        print(
            f"  {name:<28} {min(data):>14} / {sum(data) / len(data):>9.2f} / {max(data):>9} {sum(data):>8} "
            f"{dictionary:>10}  {','.join(versions)}"
        )


for argument in sys.argv[1:]:
    if os.path.isdir(argument):
        for root, _, files in sorted(os.walk(argument)):
            for name in sorted(files):
                if name.endswith(".parquet"):
                    report(os.path.join(root, name))
    else:
        report(argument)
