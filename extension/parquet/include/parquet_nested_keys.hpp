//===----------------------------------------------------------------------===//
//                         DuckDB
//
// parquet_nested_keys.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb.hpp"
#include "duckdb/common/optional_idx.hpp"
#include "duckdb/common/optional_ptr.hpp"
#include "duckdb/common/types/selection_vector.hpp"
#include "duckdb/function/table_function.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "parquet_column_schema.hpp"

namespace duckdb {
class ParquetReader;

//! A primitive column directly in a node, read flat with one row per slot of its levels
struct ParquetNodeLeaf {
	string name;
	optional_ptr<const ParquetColumnSchema> schema;
};

//! A repeated field of a nested Parquet file, read as a flat relation in which surrogate and ancestor keys connect
//! it to the other nesting levels ("Nested Parquet Is Flat, Why Not Use It?", Rey et al., SIGMOD 2025)
struct ParquetNodeInfo {
	//! The nesting level of the node - the top-level rows of the file are level 0
	idx_t level = 0;
	//! Slots with at least this definition level hold an element of the node, the others are empty placeholders
	idx_t define_level = 0;
	//! The primitive columns directly in the node (fields of non-repeated structs are flattened as "a.b")
	vector<ParquetNodeLeaf> leaves;
	//! The column whose levels are read when no column of the node is projected
	optional_ptr<const ParquetColumnSchema> key_leaf;
	//! For every level 1..level: a column directly in the node of that level, or nullptr if it has none
	vector<optional_ptr<const ParquetColumnSchema>> level_witness;
	//! Whether the elements of the node are primitive values (a list of primitives) rather than structs
	bool element_is_leaf = false;

public:
	//! Resolve a dotted path (e.g. "posts.comments") to a node - the empty path is the top level
	static ParquetNodeInfo Resolve(const ParquetColumnSchema &root, const string &path);
	//! The name of the key column of the given level
	string KeyName(idx_t key_level) const;
};

//! A node of a nested file, as read_parquet_flat exposes it
struct ParquetFlatNode {
	//! The path of the node, as read_parquet_node takes it - empty for the top level
	string path;
	idx_t level = 0;
	//! The node this node is nested in - invalid for the top level
	optional_idx parent;
	//! The columns of the node, in the order read_parquet_node returns them
	vector<string> leaf_names;
	vector<LogicalType> leaf_types;
	//! The names read_parquet_flat gives these columns: their path in the file
	vector<string> column_names;

public:
	//! All nodes of a file in preorder - MAP fields are not included
	static vector<ParquetFlatNode> EnumerateNodes(const ParquetColumnSchema &root);
};

//! Assigns the surrogate key (the row number in the node) and the ancestor keys (the row numbers of the enclosing
//! nodes) to the slots of a node, from their repetition and definition levels
class ParquetNodeKeyGenerator {
public:
	ParquetNodeKeyGenerator(idx_t level, idx_t define_level, bool include_empty);

public:
	//! Start a row group - row_offsets[k] is the number of level k rows in the preceding row groups
	void BeginRowGroup(const vector<idx_t> &row_offsets);
	//! Select the slots that are rows of the node, and compute their keys into "keys"
	idx_t Process(const uint8_t *repeats, const uint8_t *defines, idx_t count, SelectionVector &sel);
	//! After a row group: the first level whose row count differs from the expected one, if any
	optional_idx FindMismatch(const vector<optional_idx> &expected_counts) const;
	//! The number of rows of a level counted in the current row group so far
	idx_t RowCount(idx_t key_level) const;

public:
	//! keys[k][i] is the level k key of the i-th selected row - keys[level] is the surrogate key
	vector<vector<int64_t>> keys;

private:
	idx_t level;
	idx_t define_level;
	bool include_empty;
	//! The key of the current row of every level
	vector<int64_t> counters;
	//! The key of the first row of every level in the current row group
	vector<idx_t> row_group_offsets;
};

//! The number of rows of every level of a node in the row groups of a file
struct ParquetNodeRowGroupRows {
	//! offsets[rg][k]: the number of level k rows in the row groups before rg
	vector<vector<idx_t>> offsets;
	//! counts[rg][k]: the number of level k rows in row group rg - unknown for the last row group of a level that
	//! has no column of its own
	vector<vector<optional_idx>> counts;

public:
	static ParquetNodeRowGroupRows Compute(ClientContext &context, const ParquetReader &reader,
	                                       const ParquetNodeInfo &node);
};

//! read_parquet_node(file, node := 'a.b') - reads a node of a nested file as a flat relation with key columns
struct ReadParquetNodeFunction {
	static TableFunction GetFunction();
	//! A scan of a node, bound as if read_parquet_node(file, node := node_path) was called
	static unique_ptr<LogicalGet> CreateGet(ClientContext &context, TableIndex table_index, const string &file,
	                                        const string &node_path);
};

//! read_parquet_flat(file) - all columns of a nested file by their path, joining the nodes of the referenced columns
struct ReadParquetFlatFunction {
	static TableFunction GetFunction();
	//! The optimizer extension that replaces read_parquet_flat by scans of its nodes and the joins between them
	static void RegisterOptimizer(DBConfig &config);
};

} // namespace duckdb
