# Nested Parquet files whose columns have pages of different sizes, for the parallel scan of read_parquet_node
# (test/sql/copy/parquet/nested_keys/read_parquet_node_pages.test). The DuckDB writer puts a list of structs and a list
# of lists into a single page, so these files are written with pyarrow.
#
# Written with pyarrow 26.0.0 (Python 3.12). Other versions may cut the pages elsewhere: the test checks in its log
# messages at which column the parts start and in which one the rows are counted, and has to be adapted if they change.
# To regenerate the files next to this script:
#
#   python3 -m venv /tmp/pyarrow-env
#   /tmp/pyarrow-env/bin/pip install pyarrow==26.0.0
#   /tmp/pyarrow-env/bin/python data/parquet-testing/nested_pages/generate.py
#
# It writes nested_pages_v1.parquet and nested_pages_v2.parquet (about 180 KB each) into this directory.
#
# In the node "l" (a list of structs), "a" has many small pages (distinct values, no dictionary), "b" few large pages
# (dictionary encoded, few distinct values) and "c" pages of a third size; "m" is a list of lists. Some lists are NULL
# and some are empty.
import os

import pyarrow as pa
import pyarrow.parquet as pq

ROWS = 6000

ids = []
lists = []
lists_of_lists = []
for i in range(ROWS):
    ids.append(i)
    if i % 11 == 0:
        lists.append(None)
    else:
        lists.append([{"a": i * 10 + j, "b": (i + j) % 3, "c": f"value {i}-{j}"} for j in range(i % 4)])
    if i % 13 == 0:
        lists_of_lists.append(None)
    else:
        lists_of_lists.append([list(range(i % 5, i % 5 + j)) for j in range(i % 3)])

table = pa.table(
    {
        "id": pa.array(ids, pa.int64()),
        "l": pa.array(lists, pa.list_(pa.struct([("a", pa.int64()), ("b", pa.int8()), ("c", pa.string())]))),
        "m": pa.array(lists_of_lists, pa.list_(pa.list_(pa.int32()))),
    }
)

# data pages version 1 in a single row group, and version 2 (levels outside the compressed data) in three
directory = os.path.dirname(os.path.abspath(__file__))
for version, row_group_size in [("1.0", ROWS), ("2.0", 2500)]:
    pq.write_table(
        table,
        os.path.join(directory, f"nested_pages_v{version[0]}.parquet"),
        row_group_size=row_group_size,
        data_page_size=256,
        write_batch_size=16,
        data_page_version=version,
        use_dictionary=["l.list.element.b"],
        compression="snappy",
    )
