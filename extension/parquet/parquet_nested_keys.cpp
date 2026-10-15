#include "parquet_nested_keys.hpp"

#include "column_reader.hpp"
#include "parquet_reader.hpp"
#include "duckdb/common/string_util.hpp"
#include "duckdb/common/types/data_chunk.hpp"

namespace duckdb {

static bool IsRepeatedSchema(const ParquetColumnSchema &schema) {
	auto id = schema.type.id();
	return id == LogicalTypeId::LIST || id == LogicalTypeId::MAP;
}

static bool IsLeafSchema(const ParquetColumnSchema &schema) {
	return schema.schema_type == ParquetColumnSchemaType::COLUMN && schema.children.empty();
}

//! Collect the primitive columns of an element that are not inside a further repeated field
static void CollectNodeLeaves(const ParquetColumnSchema &element, const string &name, vector<ParquetNodeLeaf> &result) {
	if (element.schema_type != ParquetColumnSchemaType::COLUMN || IsRepeatedSchema(element)) {
		return;
	}
	if (IsLeafSchema(element)) {
		result.push_back(ParquetNodeLeaf {name, element});
		return;
	}
	for (auto &child : element.children) {
		CollectNodeLeaves(child, name.empty() ? child.name : name + "." + child.name, result);
	}
}

//! The first primitive column below a schema, also inside repeated fields
static optional_ptr<const ParquetColumnSchema> FindAnyLeaf(const ParquetColumnSchema &schema) {
	if (IsLeafSchema(schema)) {
		return schema;
	}
	for (auto &child : schema.children) {
		auto result = FindAnyLeaf(child);
		if (result) {
			return result;
		}
	}
	return nullptr;
}

ParquetNodeInfo ParquetNodeInfo::Resolve(const ParquetColumnSchema &root, const string &path) {
	ParquetNodeInfo result;
	result.level_witness.emplace_back();
	reference<const ParquetColumnSchema> element(root);
	string node_name;
	bool at_node = true;
	if (!path.empty()) {
		for (auto &segment : StringUtil::Split(path, '.')) {
			optional_ptr<const ParquetColumnSchema> child;
			if (IsRepeatedSchema(element.get())) {
				// the elements of a list of lists are referred to as "element"
				if (StringUtil::CIEquals(segment, "element")) {
					child = element.get();
				}
			} else {
				for (auto &entry : element.get().children) {
					if (StringUtil::CIEquals(entry.name, segment)) {
						child = entry;
						break;
					}
				}
			}
			if (!child) {
				throw BinderException("read_parquet_node: field \"%s\" of node path \"%s\" not found", segment, path);
			}
			node_name = child.get() == &element.get() ? "element" : child->name;
			if (child->type.id() == LogicalTypeId::MAP) {
				throw NotImplementedException("read_parquet_node: MAP field \"%s\" cannot be read as a node", segment);
			}
			if (child->type.id() == LogicalTypeId::LIST) {
				D_ASSERT(child->children.size() == 1);
				result.level = child->max_repeat;
				result.define_level = child->max_define;
				element = child->children[0];
				vector<ParquetNodeLeaf> direct_leaves;
				CollectNodeLeaves(element.get(), string(), direct_leaves);
				result.level_witness.push_back(direct_leaves.empty() ? optional_ptr<const ParquetColumnSchema>()
				                                                     : direct_leaves[0].schema);
				D_ASSERT(result.level_witness.size() == result.level + 1);
				at_node = true;
			} else if (child->type.id() == LogicalTypeId::STRUCT &&
			           child->schema_type == ParquetColumnSchemaType::COLUMN) {
				element = *child;
				at_node = false;
			} else {
				throw BinderException("read_parquet_node: field \"%s\" of node path \"%s\" is not a list or struct",
				                      segment, path);
			}
		}
	}
	if (!at_node) {
		throw BinderException("read_parquet_node: node path \"%s\" does not end at a repeated field", path);
	}
	CollectNodeLeaves(element.get(), IsLeafSchema(element.get()) ? node_name : string(), result.leaves);
	result.key_leaf = result.leaves.empty() ? FindAnyLeaf(element.get()) : result.leaves[0].schema;
	if (!result.key_leaf) {
		throw BinderException("read_parquet_node: node \"%s\" has no columns", path);
	}
	return result;
}

string ParquetNodeInfo::KeyName(idx_t key_level) const {
	if (key_level == level) {
		return "_sk";
	}
	return "_ak" + to_string(key_level);
}

ParquetNodeKeyGenerator::ParquetNodeKeyGenerator(idx_t level, idx_t define_level, bool include_empty)
    : level(level), define_level(define_level), include_empty(include_empty) {
	keys.resize(level + 1);
	for (auto &key : keys) {
		key.resize(STANDARD_VECTOR_SIZE);
	}
	counters.resize(level + 1);
}

void ParquetNodeKeyGenerator::BeginRowGroup(const vector<idx_t> &row_offsets) {
	D_ASSERT(row_offsets.size() == level + 1);
	// the first slot of a row group starts a new row on every level
	for (idx_t k = 0; k <= level; k++) {
		counters[k] = NumericCast<int64_t>(row_offsets[k]) - 1;
	}
}

idx_t ParquetNodeKeyGenerator::Process(const uint8_t *repeats, const uint8_t *defines, idx_t count,
                                       SelectionVector &sel) {
	idx_t result_count = 0;
	for (idx_t i = 0; i < count; i++) {
		const idx_t repeat = repeats[i];
		// a slot repeated at level r starts a new row on every level >= r
		for (idx_t k = repeat; k <= level; k++) {
			counters[k]++;
		}
		if (repeat > level) {
			// the slot continues a row of the node in a deeper level
			continue;
		}
		if (defines[i] < define_level && !include_empty) {
			continue;
		}
		sel.set_index(result_count, i);
		for (idx_t k = 0; k <= level; k++) {
			keys[k][result_count] = counters[k];
		}
		result_count++;
	}
	return result_count;
}

//! Count the slots that start a row on the given levels in a row group, by reading the levels of a column
static void CountLevelRows(const ParquetReader &reader, const ParquetColumnSchema &leaf, idx_t row_group_idx,
                           TProtocol &protocol, const vector<idx_t> &levels, vector<idx_t> &result) {
	auto &group = reader.GetFileMetadata()->row_groups[row_group_idx];
	auto column_reader = ColumnReader::CreateReader(reader, leaf);
	column_reader->InitializeRead(row_group_idx, NumericCast<idx_t>(group.num_rows), group.columns, protocol);

	ResizeableBuffer define_buf(reader.allocator, STANDARD_VECTOR_SIZE);
	ResizeableBuffer repeat_buf(reader.allocator, STANDARD_VECTOR_SIZE);
	auto defines = reinterpret_cast<uint8_t *>(define_buf.ptr);
	auto repeats = reinterpret_cast<uint8_t *>(repeat_buf.ptr);
	DataChunk chunk;
	chunk.Initialize(reader.allocator, {leaf.type});
	while (column_reader->GroupRowsAvailable() > 0) {
		auto count = MinValue<idx_t>(STANDARD_VECTOR_SIZE, column_reader->GroupRowsAvailable());
		chunk.Reset();
		chunk.SetChildCardinality(count);
		define_buf.zero();
		repeat_buf.zero();
		ColumnReaderInput input(count, defines, repeats);
		column_reader->Read(input, chunk.data[0]);
		for (idx_t i = 0; i < count; i++) {
			for (auto level : levels) {
				result[level] += repeats[i] <= level;
			}
		}
	}
}

vector<vector<idx_t>> ComputeNodeRowOffsets(ClientContext &context, const ParquetReader &reader,
                                            const ParquetNodeInfo &node) {
	auto &row_groups = reader.GetFileMetadata()->row_groups;
	// levels whose node has no column of its own have no row count in the metadata - their rows are counted
	vector<idx_t> counted_levels;
	for (idx_t k = 1; k <= node.level; k++) {
		if (!node.level_witness[k]) {
			counted_levels.push_back(k);
		}
	}
	unique_ptr<TProtocol> protocol;
	if (!counted_levels.empty() && row_groups.size() > 1) {
		protocol = reader.OpenColumnProtocol(context);
	}

	vector<vector<idx_t>> result;
	vector<idx_t> row_counts(node.level + 1, 0);
	for (idx_t rg = 0; rg < row_groups.size(); rg++) {
		result.push_back(row_counts);
		if (rg + 1 == row_groups.size()) {
			break;
		}
		auto &group = row_groups[rg];
		row_counts[0] += NumericCast<idx_t>(group.num_rows);
		for (idx_t k = 1; k <= node.level; k++) {
			auto &witness = node.level_witness[k];
			if (witness) {
				// every slot of a column directly in the node starts a row of it (or an empty placeholder)
				row_counts[k] += NumericCast<idx_t>(group.columns[witness->column_index].meta_data.num_values);
			}
		}
		if (!counted_levels.empty()) {
			CountLevelRows(reader, *node.key_leaf, rg, *protocol, counted_levels, row_counts);
		}
	}
	return result;
}

} // namespace duckdb
