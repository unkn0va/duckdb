#!/usr/bin/env python3
"""Write the trade fact Parquet files from the distinct rows and the shuffled row order made by prepare_trade.sh.

Input (made with DuckDB by prepare_trade.sh):
  distinct.parquet  the distinct rows of the CSV, typed, in the order of idx (0, 1, ...), with their count n
  order.parquet     one row per row of the CSV: the idx of its distinct row, in the shuffled order (optional; without
                    it, every distinct row is written once, in idx order - the "distinct" version)

Output files, all with the same writer settings (WRITER below: pyarrow 26.0.0 defaults, snappy) and row groups of
exactly ROW_GROUP_ROWS rows (the last one is smaller):
  A   trade_A.parquet   c0..c22, the lists c11..c18 as independent lists
  B   trade_B.parquet   c0..c14, legs LIST<STRUCT<leg_id, currency, option_type, value>> (c15..c18 zipped), c19..c22
  C   trade_C.parquet   B with c11, c12, c13 wrapped as LIST<STRUCT<v BIGINT>> (for pre-nest, which needs struct elements)
  flat  pureflat/parent.parquet  sk (row number in B, from 0) and the scalar columns
        pureflat/<list>.parquet  ak0 (the parent's sk) and the element, one row per element: c11, c12, c13, c14, and
                                 legs with the four fields - rows in the order of the parent and of the list

Usage: write_trade.py <distinct.parquet> <order.parquet | -> <out dir> <A|B|C|flat>
       write_trade.py --rewrite <in.parquet> <out.parquet>   (any small file, e.g. the dimension tables)
"""
import os
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROW_GROUP_ROWS = 122_880
CHUNK_ROWS = ROW_GROUP_ROWS * 8
# Only compression is set; everything else is pyarrow's default, as in the rg1/rg20 files of followup_checks.sh.
WRITER = {"compression": "snappy"}

LISTS = ["c11", "c12", "c13", "c14"]
WRAPPED = ["c11", "c12", "c13"]
LEG_COLUMNS = {"c15": "leg_id", "c16": "currency", "c17": "option_type", "c18": "value"}
SCALARS = [f"c{i}" for i in list(range(0, 11)) + list(range(19, 23))]


class RowGroupWriter:
    """A ParquetWriter that writes row groups of exactly ROW_GROUP_ROWS rows, whatever the size of the tables given."""

    def __init__(self, path, schema):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.writer = pq.ParquetWriter(path + ".partial", schema, **WRITER)
        self.pending = []
        self.pending_rows = 0
        self.rows = 0

    def write(self, table):
        self.pending.append(table)
        self.pending_rows += table.num_rows
        while self.pending_rows >= ROW_GROUP_ROWS:
            self._flush(ROW_GROUP_ROWS)

    def _flush(self, rows):
        table = pa.concat_tables(self.pending)
        self.writer.write_table(table.slice(0, rows), row_group_size=ROW_GROUP_ROWS)
        rest = table.slice(rows)
        self.pending = [rest] if rest.num_rows else []
        self.pending_rows = rest.num_rows
        self.rows += rows

    def close(self):
        if self.pending_rows:
            self._flush(self.pending_rows)
        self.writer.close()
        os.replace(self.path + ".partial", self.path)


def plain_list(column):
    """The list column as one ListArray with offsets from 0 (take() and slicing leave them shifted)."""
    array = column.combine_chunks() if isinstance(column, pa.ChunkedArray) else column
    if array.null_count:
        raise SystemExit(f"unexpected NULL lists in {column}")
    lengths = pc.list_value_length(array).cast(pa.int32())
    offsets = pa.concat_arrays([pa.array([0], pa.int32()), pc.cumulative_sum(lengths)])
    return pa.ListArray.from_arrays(offsets, array.flatten()), lengths


def legs(chunk):
    """c15..c18 zipped into LIST<STRUCT>; stops when the four lists of a row differ in length."""
    lists = [plain_list(chunk[c]) for c in LEG_COLUMNS]
    lengths = lists[0][1]
    for (_, other), name in zip(lists[1:], list(LEG_COLUMNS)[1:]):
        if not pc.all(pc.equal(lengths, other)).as_py():
            raise SystemExit(f"legs: c15 and {name} differ in length in a row")
    struct = pa.StructArray.from_arrays([array.values for array, _ in lists], names=list(LEG_COLUMNS.values()))
    return pa.ListArray.from_arrays(lists[0][0].offsets, struct), lengths


def to_c(chunk):
    table = to_b(chunk)
    for name in WRAPPED:
        array, _ = plain_list(table[name])
        wrapped = pa.ListArray.from_arrays(array.offsets, pa.StructArray.from_arrays([array.values], names=["v"]))
        table = table.set_column(table.column_names.index(name), name, wrapped)
    return table


def parent_keys(array, first_sk):
    """The sk of the parent row of every element of the list array, whose first row has the sk first_sk."""
    return pc.add(pc.list_parent_indices(array).cast(pa.int64()), first_sk)


def to_b(chunk):
    columns = [c for c in chunk.column_names if c not in LEG_COLUMNS]
    table = chunk.select(columns)
    position = columns.index("c19")
    return table.add_column(position, "legs", legs(chunk)[0])


def chunks(distinct_path, order_path):
    table = pq.read_table(distinct_path)
    if table["idx"].to_pylist() != list(range(table.num_rows)):
        raise SystemExit(f"{distinct_path}: idx is not 0, 1, ... in file order")
    table = table.drop_columns(["idx", "n", "h"])
    if order_path == "-":
        for start in range(0, table.num_rows, CHUNK_ROWS):
            yield table.slice(start, CHUNK_ROWS)
        return
    for batch in pq.ParquetFile(order_path).iter_batches(batch_size=CHUNK_ROWS, columns=["idx"]):
        yield table.take(batch.column(0))


def main():
    if sys.argv[1] == "--rewrite":
        source, target = sys.argv[2:4]
        table = pq.read_table(source)
        writer = RowGroupWriter(target, table.schema)
        writer.write(table)
        writer.close()
        print(f"{target}: {table.num_rows} rows")
        return

    distinct_path, order_path, out, part = sys.argv[1:5]
    writers = {}

    def write(name, table):
        if name not in writers:
            writers[name] = RowGroupWriter(os.path.join(out, name), table.schema)
        writers[name].write(table)

    sk = 0
    for chunk in chunks(distinct_path, order_path):
        if part == "A":
            write("trade_A.parquet", chunk)
        elif part == "B":
            write("trade_B.parquet", to_b(chunk))
        elif part == "C":
            write("trade_C.parquet", to_c(chunk))
        elif part == "flat":
            keys = pa.array(range(sk, sk + chunk.num_rows), pa.int64())
            write("pureflat/parent.parquet", chunk.select(SCALARS).add_column(0, "sk", keys))
            for name in LISTS:
                array, _ = plain_list(chunk[name])
                write(f"pureflat/{name}.parquet", pa.table({"ak0": parent_keys(array, sk), name: array.values}))
            array, _ = legs(chunk)
            elements = pa.Table.from_struct_array(array.values)
            write("pureflat/legs.parquet", elements.add_column(0, "ak0", parent_keys(array, sk)))
        else:
            raise SystemExit(f"unknown part {part}")
        sk += chunk.num_rows

    for name, writer in writers.items():
        writer.close()
        print(f"{os.path.join(out, name)}: {writer.rows} rows")


if __name__ == "__main__":
    main()
