#include "parquet_nested_keys.hpp"

#include "column_reader.hpp"
#include "parquet_reader.hpp"
#include "duckdb/common/string_util.hpp"
#include "duckdb/common/types/data_chunk.hpp"
#include "duckdb/common/vector/constant_vector.hpp"
#include "duckdb/common/vector/flat_vector.hpp"
#include "duckdb/common/vector/vector_writer.hpp"
#include "duckdb/function/table_function.hpp"

namespace duckdb {

struct ReadParquetNodeData : public TableFunctionData {
	shared_ptr<ParquetReader> reader;
	ParquetNodeInfo node;
	bool include_empty = false;
	idx_t cardinality = 0;
};

//! What a projected column of the scan is read from
struct ReadParquetNodeColumn {
	enum class Kind : uint8_t { LEAF, KEY, OTHER };
	Kind kind;
	//! The position of the leaf among the readers, or the level of the key
	idx_t index;
};

struct ReadParquetNodeGlobalState : public GlobalTableFunctionState {
	vector<vector<idx_t>> row_offsets;
	vector<ReadParquetNodeColumn> columns;
	//! The columns that are read - the first one drives the keys
	vector<reference<const ParquetColumnSchema>> read_leaves;
	atomic<idx_t> next_row_group {0};
	idx_t max_threads = 1;

	idx_t MaxThreads() const override {
		return max_threads;
	}
};

struct ReadParquetNodeLocalState : public LocalTableFunctionState {
	ReadParquetNodeLocalState(const ParquetNodeInfo &node, bool include_empty)
	    : generator(node.level, node.define_level, include_empty) {
	}

	unique_ptr<TProtocol> protocol;
	bool has_row_group = false;
	vector<unique_ptr<ColumnReader>> readers;
	DataChunk read_chunk;
	ResizeableBuffer define_buf;
	ResizeableBuffer repeat_buf;
	ResizeableBuffer scratch_define_buf;
	ResizeableBuffer scratch_repeat_buf;
	ParquetNodeKeyGenerator generator;
};

static unique_ptr<FunctionData> ReadParquetNodeBind(ClientContext &context, TableFunctionBindInput &input,
                                                    vector<LogicalType> &return_types, vector<Identifier> &names) {
	if (input.inputs[0].IsNull()) {
		throw BinderException("read_parquet_node requires a non-NULL file name");
	}
	auto result = make_uniq<ReadParquetNodeData>();
	string node_path;
	for (auto &kv : input.named_parameters) {
		if (kv.second.IsNull()) {
			throw BinderException("read_parquet_node: parameter \"%s\" cannot be NULL", kv.first.GetIdentifierName());
		}
		auto name = StringUtil::Lower(kv.first.GetIdentifierName());
		if (name == "node") {
			node_path = kv.second.GetValue<string>();
		} else if (name == "include_empty") {
			result->include_empty = BooleanValue::Get(kv.second);
		}
	}
	OpenFileInfo file(input.inputs[0].GetValue<string>());
	result->reader = make_shared_ptr<ParquetReader>(context, file, ParquetOptions(context));
	auto &reader = *result->reader;
	if (reader.metadata->crypto_metadata) {
		throw NotImplementedException("read_parquet_node does not support encrypted Parquet files");
	}
	result->node = ParquetNodeInfo::Resolve(*reader.root_schema, node_path);
	auto &node = result->node;

	for (auto &leaf : node.leaves) {
		names.emplace_back(leaf.name);
		return_types.push_back(leaf.schema->type);
	}
	names.emplace_back(node.KeyName(node.level));
	return_types.push_back(LogicalType::BIGINT);
	for (idx_t k = 0; k < node.level; k++) {
		names.emplace_back(node.KeyName(k));
		return_types.push_back(LogicalType::BIGINT);
	}

	// the slots of a column directly in the node are its rows (and placeholders) - otherwise this is an upper bound
	auto &cardinality_leaf = node.leaves.empty() ? *node.key_leaf : *node.leaves[0].schema;
	for (auto &group : reader.GetFileMetadata()->row_groups) {
		result->cardinality += node.level == 0 ? NumericCast<idx_t>(group.num_rows)
		                                       : NumericCast<idx_t>(
		                                             group.columns[cardinality_leaf.column_index].meta_data.num_values);
	}
	return std::move(result);
}

static unique_ptr<GlobalTableFunctionState> ReadParquetNodeInitGlobal(ClientContext &context,
                                                                      TableFunctionInitInput &input) {
	auto &data = input.bind_data->Cast<ReadParquetNodeData>();
	auto &node = data.node;
	auto result = make_uniq<ReadParquetNodeGlobalState>();

	const auto leaf_count = node.leaves.size();
	for (auto &column_id : input.column_ids) {
		if (column_id < leaf_count) {
			result->columns.push_back({ReadParquetNodeColumn::Kind::LEAF, result->read_leaves.size()});
			result->read_leaves.push_back(*node.leaves[column_id].schema);
		} else if (column_id < leaf_count + node.level + 1) {
			// the surrogate key comes first, followed by the ancestor keys of levels 0, 1, ...
			auto key_index = column_id - leaf_count;
			auto level = key_index == 0 ? node.level : key_index - 1;
			result->columns.push_back({ReadParquetNodeColumn::Kind::KEY, level});
		} else {
			result->columns.push_back({ReadParquetNodeColumn::Kind::OTHER, 0});
		}
	}
	if (result->read_leaves.empty()) {
		// only keys are projected - read the levels of any column of the node
		result->read_leaves.push_back(*node.key_leaf);
	}
	result->row_offsets = ComputeNodeRowOffsets(context, *data.reader, node);
	result->max_threads = MaxValue<idx_t>(data.reader->NumRowGroups(), 1);
	return std::move(result);
}

static unique_ptr<LocalTableFunctionState> ReadParquetNodeInitLocal(ExecutionContext &context,
                                                                    TableFunctionInitInput &input,
                                                                    GlobalTableFunctionState *global_state) {
	auto &data = input.bind_data->Cast<ReadParquetNodeData>();
	auto &gstate = global_state->Cast<ReadParquetNodeGlobalState>();
	auto &reader = *data.reader;
	auto result = make_uniq<ReadParquetNodeLocalState>(data.node, data.include_empty);
	vector<LogicalType> read_types;
	for (auto &leaf : gstate.read_leaves) {
		read_types.push_back(leaf.get().type);
	}
	result->read_chunk.Initialize(reader.allocator, read_types);
	result->define_buf.resize(reader.allocator, STANDARD_VECTOR_SIZE);
	result->repeat_buf.resize(reader.allocator, STANDARD_VECTOR_SIZE);
	result->scratch_define_buf.resize(reader.allocator, STANDARD_VECTOR_SIZE);
	result->scratch_repeat_buf.resize(reader.allocator, STANDARD_VECTOR_SIZE);
	return std::move(result);
}

//! Claim the next row group, and start reading its columns
static bool ReadParquetNodeNextRowGroup(ClientContext &context, const ReadParquetNodeData &data,
                                        ReadParquetNodeGlobalState &gstate, ReadParquetNodeLocalState &lstate) {
	auto &reader = *data.reader;
	auto row_group_idx = gstate.next_row_group++;
	if (row_group_idx >= reader.NumRowGroups()) {
		return false;
	}
	if (!lstate.protocol) {
		lstate.protocol = reader.OpenColumnProtocol(context);
	}
	auto &group = reader.GetFileMetadata()->row_groups[row_group_idx];
	lstate.readers.clear();
	for (auto &leaf : gstate.read_leaves) {
		auto column_reader = ColumnReader::CreateReader(reader, leaf.get());
		column_reader->InitializeRead(row_group_idx, NumericCast<idx_t>(group.num_rows), group.columns,
		                              *lstate.protocol);
		lstate.readers.push_back(std::move(column_reader));
	}
	lstate.generator.BeginRowGroup(gstate.row_offsets[row_group_idx]);
	lstate.has_row_group = true;
	return true;
}

static void ReadParquetNodeScan(ClientContext &context, TableFunctionInput &input, DataChunk &output) {
	auto &data = input.bind_data->Cast<ReadParquetNodeData>();
	auto &gstate = input.global_state->Cast<ReadParquetNodeGlobalState>();
	auto &lstate = input.local_state->Cast<ReadParquetNodeLocalState>();

	auto defines = reinterpret_cast<uint8_t *>(lstate.define_buf.ptr);
	auto repeats = reinterpret_cast<uint8_t *>(lstate.repeat_buf.ptr);
	auto scratch_defines = reinterpret_cast<uint8_t *>(lstate.scratch_define_buf.ptr);
	auto scratch_repeats = reinterpret_cast<uint8_t *>(lstate.scratch_repeat_buf.ptr);
	while (true) {
		if (!lstate.has_row_group && !ReadParquetNodeNextRowGroup(context, data, gstate, lstate)) {
			return;
		}
		// all columns of the node have the same slots - the first one determines how many there are left
		auto &key_reader = *lstate.readers[0];
		auto count = MinValue<idx_t>(STANDARD_VECTOR_SIZE, key_reader.GroupRowsAvailable());
		if (count == 0) {
			lstate.has_row_group = false;
			continue;
		}
		lstate.read_chunk.Reset();
		lstate.read_chunk.SetChildCardinality(count);
		for (idx_t i = 0; i < lstate.readers.size(); i++) {
			// columns without repetition or definition levels do not write them - they are all zero then
			auto define_ptr = i == 0 ? defines : scratch_defines;
			auto repeat_ptr = i == 0 ? repeats : scratch_repeats;
			memset(define_ptr, 0, count);
			memset(repeat_ptr, 0, count);
			ColumnReaderInput reader_input(count, define_ptr, repeat_ptr);
			auto read_count = lstate.readers[i]->Read(reader_input, lstate.read_chunk.data[i]);
			if (read_count != count) {
				throw InvalidInputException("read_parquet_node: mismatch in the number of values of the columns of "
				                            "node \"%s\" in file \"%s\"",
				                            lstate.readers[i]->Schema().name, data.reader->GetFileName());
			}
		}

		SelectionVector sel(STANDARD_VECTOR_SIZE);
		auto result_count = lstate.generator.Process(repeats, defines, count, sel);
		if (result_count == 0) {
			continue;
		}
		for (idx_t col_idx = 0; col_idx < gstate.columns.size(); col_idx++) {
			auto &column = gstate.columns[col_idx];
			auto &result = output.data[col_idx];
			switch (column.kind) {
			case ReadParquetNodeColumn::Kind::LEAF:
				if (result_count == count) {
					result.Reference(lstate.read_chunk.data[column.index]);
				} else {
					result.Slice(lstate.read_chunk.data[column.index], sel, result_count);
				}
				break;
			case ReadParquetNodeColumn::Kind::KEY: {
				auto &keys = lstate.generator.keys[column.index];
				auto writer = FlatVector::Writer<int64_t>(result, result_count);
				for (idx_t i = 0; i < result_count; i++) {
					writer.WriteValue(keys[i]);
				}
				break;
			}
			default:
				ConstantVector::SetNull(result, count_t(result_count));
				break;
			}
		}
		output.SetChildCardinality(result_count);
		return;
	}
}

static unique_ptr<NodeStatistics> ReadParquetNodeCardinality(ClientContext &context, const FunctionData *bind_data) {
	auto &data = bind_data->Cast<ReadParquetNodeData>();
	return make_uniq<NodeStatistics>(data.cardinality);
}

TableFunction ReadParquetNodeFunction::GetFunction() {
	TableFunction function("read_parquet_node", FunctionSignature().AddPositionalOnly("file", LogicalType::VARCHAR),
	                       ReadParquetNodeScan, ReadParquetNodeBind, ReadParquetNodeInitGlobal,
	                       ReadParquetNodeInitLocal);
	function.GetSignature()
	    .AddKeywordOnly("node", LogicalType::VARCHAR, Value(""))
	    .AddKeywordOnly("include_empty", LogicalType::BOOLEAN, Value::BOOLEAN(false));
	function.cardinality = ReadParquetNodeCardinality;
	function.projection_pushdown = true;
	return function;
}

} // namespace duckdb
