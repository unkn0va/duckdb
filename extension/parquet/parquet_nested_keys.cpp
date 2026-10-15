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
	result.element_is_leaf = IsLeafSchema(element.get());
	CollectNodeLeaves(element.get(), result.element_is_leaf ? node_name : string(), result.leaves);
	result.key_leaf = result.leaves.empty() ? FindAnyLeaf(element.get()) : result.leaves[0].schema;
	if (!result.key_leaf) {
		throw BinderException("read_parquet_node: node \"%s\" has no columns", path);
	}
	return result;
}

//! Collect the nodes below an element of the node with the given index
static void EnumerateChildNodes(const ParquetColumnSchema &root, const ParquetColumnSchema &element,
                                const string &path, idx_t node_idx, vector<ParquetFlatNode> &result);

static void AddFlatNode(const ParquetColumnSchema &root, const ParquetColumnSchema &list, const string &path,
                        optional_idx parent, vector<ParquetFlatNode> &result) {
	auto node = ParquetNodeInfo::Resolve(root, path);
	ParquetFlatNode flat_node;
	flat_node.path = path;
	flat_node.level = node.level;
	flat_node.parent = parent;
	for (auto &leaf : node.leaves) {
		flat_node.leaf_names.push_back(leaf.name);
		flat_node.leaf_types.push_back(leaf.schema->type);
		if (path.empty()) {
			flat_node.column_names.push_back(leaf.name);
		} else if (node.element_is_leaf) {
			// the elements of a list of primitives are the node itself
			flat_node.column_names.push_back(path);
		} else {
			flat_node.column_names.push_back(path + "." + leaf.name);
		}
	}
	// the path is resolved case-insensitively - make sure it leads to this node
	if (parent.IsValid() && node.level != result[parent.GetIndex()].level + 1) {
		throw BinderException("read_parquet_flat: the nested field \"%s\" cannot be told apart from another field",
		                      path);
	}
	auto node_idx = result.size();
	result.push_back(std::move(flat_node));
	if (list.type.id() == LogicalTypeId::LIST) {
		EnumerateChildNodes(root, list.children[0], path, node_idx, result);
	} else {
		EnumerateChildNodes(root, list, path, node_idx, result);
	}
}

static void EnumerateChildNodes(const ParquetColumnSchema &root, const ParquetColumnSchema &element,
                                const string &path, idx_t node_idx, vector<ParquetFlatNode> &result) {
	if (element.schema_type != ParquetColumnSchemaType::COLUMN) {
		return;
	}
	if (element.type.id() == LogicalTypeId::LIST) {
		// a list of lists: its elements are a node of their own
		AddFlatNode(root, element, path + ".element", node_idx, result);
		return;
	}
	if (element.type.id() != LogicalTypeId::STRUCT) {
		return;
	}
	for (auto &child : element.children) {
		auto child_path = path.empty() ? child.name : path + "." + child.name;
		if (child.type.id() == LogicalTypeId::LIST) {
			AddFlatNode(root, child, child_path, node_idx, result);
		} else if (child.type.id() == LogicalTypeId::STRUCT) {
			EnumerateChildNodes(root, child, child_path, node_idx, result);
		}
	}
}

vector<ParquetFlatNode> ParquetFlatNode::EnumerateNodes(const ParquetColumnSchema &root) {
	vector<ParquetFlatNode> result;
	AddFlatNode(root, root, string(), optional_idx(), result);
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
	row_group_offsets = row_offsets;
}

optional_idx ParquetNodeKeyGenerator::FindMismatch(const vector<optional_idx> &expected_counts) const {
	D_ASSERT(expected_counts.size() == level + 1);
	for (idx_t k = 0; k <= level; k++) {
		if (expected_counts[k].IsValid() && RowCount(k) != expected_counts[k].GetIndex()) {
			return k;
		}
	}
	return optional_idx();
}

idx_t ParquetNodeKeyGenerator::RowCount(idx_t key_level) const {
	return NumericCast<idx_t>(counters[key_level] + 1) - row_group_offsets[key_level];
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

ParquetNodeRowGroupRows ParquetNodeRowGroupRows::Compute(ClientContext &context, const ParquetReader &reader,
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

	ParquetNodeRowGroupRows result;
	vector<idx_t> offsets(node.level + 1, 0);
	for (idx_t rg = 0; rg < row_groups.size(); rg++) {
		auto &group = row_groups[rg];
		vector<optional_idx> counts(node.level + 1);
		counts[0] = NumericCast<idx_t>(group.num_rows);
		for (idx_t k = 1; k <= node.level; k++) {
			auto &witness = node.level_witness[k];
			if (witness) {
				// every slot of a column directly in the node starts a row of it (or an empty placeholder)
				counts[k] = NumericCast<idx_t>(group.columns[witness->column_index].meta_data.num_values);
			}
		}
		// the levels of the last row group are not needed for any offset - its counts stay unknown
		if (!counted_levels.empty() && rg + 1 < row_groups.size()) {
			vector<idx_t> level_counts(node.level + 1, 0);
			CountLevelRows(reader, *node.key_leaf, rg, *protocol, counted_levels, level_counts);
			for (auto k : counted_levels) {
				counts[k] = level_counts[k];
			}
		}
		result.offsets.push_back(offsets);
		for (idx_t k = 0; k <= node.level; k++) {
			if (counts[k].IsValid()) {
				offsets[k] += counts[k].GetIndex();
			}
		}
		result.counts.push_back(std::move(counts));
	}
	return result;
}

} // namespace duckdb
