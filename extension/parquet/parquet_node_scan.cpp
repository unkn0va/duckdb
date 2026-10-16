#include "parquet_nested_keys.hpp"

#include "column_reader.hpp"
#include "parquet_reader.hpp"
#include "duckdb/common/string_util.hpp"
#include "duckdb/common/types/data_chunk.hpp"
#include "duckdb/common/vector/constant_vector.hpp"
#include "duckdb/common/vector/flat_vector.hpp"
#include "duckdb/common/vector/vector_writer.hpp"
#include "duckdb/function/table_function.hpp"
#include "duckdb/parallel/task_scheduler.hpp"
#include "duckdb/parser/tableref/table_function_ref.hpp"
#include "duckdb/storage/statistics/numeric_stats.hpp"

namespace duckdb {

//! The default number of slots below which a row group is not split into parts for several threads
static constexpr idx_t DEFAULT_TASK_SLOTS = 60 * STANDARD_VECTOR_SIZE;

struct ReadParquetNodeData : public TableFunctionData {
	shared_ptr<ParquetReader> reader;
	string node_path;
	ParquetNodeInfo node;
	bool include_empty = false;
	idx_t cardinality = 0;
	//! For every level: an upper bound of the number of rows (and placeholders) of the level - the keys are below it
	vector<idx_t> key_upper_bounds;
};

//! What a projected column of the scan is read from
struct ReadParquetNodeColumn {
	enum class Kind : uint8_t { LEAF, KEY, OTHER };
	Kind kind;
	//! The position of the leaf among the readers, or the level of the key
	idx_t index;
};

struct ReadParquetNodeGlobalState : public GlobalTableFunctionState {
	ParquetNodeTaskPlan plan;
	vector<ReadParquetNodeColumn> columns;
	//! The columns that are read - the first one drives the keys
	vector<reference<const ParquetColumnSchema>> read_leaves;
	atomic<idx_t> next_task {0};
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
	//! The slots of the current row group that are left to read
	idx_t slots_left = 0;
	idx_t task_idx = 0;
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
	result->node_path = node_path;
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
	// a level without a column of its own has fewer rows than the slots of any column below it
	result->key_upper_bounds.resize(node.level + 1, 0);
	for (auto &group : reader.GetFileMetadata()->row_groups) {
		result->key_upper_bounds[0] += NumericCast<idx_t>(group.num_rows);
		for (idx_t k = 1; k <= node.level; k++) {
			auto &count_leaf = node.level_witness[k] ? *node.level_witness[k] : *node.key_leaf;
			auto &chunk_metadata = group.columns[count_leaf.column_index].meta_data;
			result->key_upper_bounds[k] += NumericCast<idx_t>(chunk_metadata.num_values);
		}
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
	vector<bool> needed_levels(node.level + 1, false);
	for (auto &column : result->columns) {
		if (column.kind == ReadParquetNodeColumn::Kind::KEY) {
			needed_levels[column.index] = true;
		}
	}
	auto threads = NumericCast<idx_t>(TaskScheduler::GetScheduler(context).NumberOfThreads());
	Value task_slots;
	idx_t min_task_slots = DEFAULT_TASK_SLOTS;
	if (context.TryGetCurrentSetting("parquet_node_task_slots", task_slots) && !task_slots.IsNull()) {
		min_task_slots = task_slots.GetValue<idx_t>();
	}
	result->plan = ParquetNodeTaskPlan::Create(context, *data.reader, node, result->read_leaves[0], needed_levels,
	                                           threads, min_task_slots);
	result->max_threads = MaxValue<idx_t>(result->plan.tasks.size(), 1);
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

//! Claim the next part of a row group, and start reading its columns
static bool ReadParquetNodeNextTask(ClientContext &context, const ReadParquetNodeData &data,
                                    ReadParquetNodeGlobalState &gstate, ReadParquetNodeLocalState &lstate) {
	auto &reader = *data.reader;
	auto task_idx = gstate.next_task++;
	if (task_idx >= gstate.plan.tasks.size()) {
		return false;
	}
	auto &task = gstate.plan.tasks[task_idx];
	auto row_group_idx = task.row_group;
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
	// the columns of a node have the same slots. The readers do not track how many are left themselves: a top-level
	// column whose values are all NULL is not read at all
	auto row_group_slots = lstate.readers[0]->GroupRowsAvailable();
	for (auto &column_reader : lstate.readers) {
		if (column_reader->GroupRowsAvailable() != row_group_slots || task.slot_end > row_group_slots) {
			throw InvalidInputException("read_parquet_node: corrupt file \"%s\": the columns of a node have a "
			                            "different number of values in row group %llu",
			                            reader.GetFileName(), row_group_idx);
		}
		// the pages before the part are skipped by their headers only
		column_reader->Skip(task.slot_start);
	}
	lstate.slots_left = task.slot_end - task.slot_start;
	lstate.generator.BeginTask(task.rows_before);
	lstate.task_idx = task_idx;
	lstate.has_row_group = true;
	return true;
}

//! The keys are offset by the row counts of the metadata (or of the levels counted before the scan) - verify that
//! the levels of the part agree with them
static void VerifyTaskRows(const ReadParquetNodeData &data, ReadParquetNodeGlobalState &gstate,
                           ReadParquetNodeLocalState &lstate) {
	auto &task = gstate.plan.tasks[lstate.task_idx];
	auto mismatch = lstate.generator.FindMismatch(task.rows_in_task);
	if (!mismatch.IsValid()) {
		return;
	}
	auto level = mismatch.GetIndex();
	auto rows = lstate.generator.RowCount(level);
	auto expected = task.rows_in_task[level].GetIndex();
	if (task.slot_start == 0) {
		throw InvalidInputException("read_parquet_node: corrupt file \"%s\": row group %llu has %llu rows on nesting "
		                            "level %llu according to its repetition levels, but %llu according to its metadata",
		                            data.reader->GetFileName(), task.row_group, rows, level, expected);
	}
	throw InvalidInputException("read_parquet_node: corrupt file \"%s\": slots %llu to %llu of row group %llu have "
	                            "%llu rows on nesting level %llu, but %llu when they were counted before",
	                            data.reader->GetFileName(), task.slot_start, task.slot_end, task.row_group, rows, level,
	                            expected);
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
		if (!lstate.has_row_group && !ReadParquetNodeNextTask(context, data, gstate, lstate)) {
			return;
		}
		auto count = MinValue<idx_t>(STANDARD_VECTOR_SIZE, lstate.slots_left);
		if (count == 0) {
			VerifyTaskRows(data, gstate, lstate);
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

		lstate.slots_left -= count;

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

//! The parts are numbered in the order of the file, so that the order of the rows can be preserved
static OperatorPartitionData ReadParquetNodePartitionData(ClientContext &context,
                                                          TableFunctionGetPartitionInput &input) {
	auto &lstate = input.local_state->Cast<ReadParquetNodeLocalState>();
	return OperatorPartitionData(lstate.task_idx);
}

static double ReadParquetNodeProgress(ClientContext &context, const FunctionData *bind_data,
                                      const GlobalTableFunctionState *global_state) {
	auto &gstate = global_state->Cast<ReadParquetNodeGlobalState>();
	if (gstate.plan.tasks.empty()) {
		return 100.0;
	}
	auto claimed = MinValue<idx_t>(gstate.next_task.load(), gstate.plan.tasks.size());
	return 100.0 * static_cast<double>(claimed) / static_cast<double>(gstate.plan.tasks.size());
}

static unique_ptr<NodeStatistics> ReadParquetNodeCardinality(ClientContext &context, const FunctionData *bind_data) {
	auto &data = bind_data->Cast<ReadParquetNodeData>();
	return make_uniq<NodeStatistics>(data.cardinality);
}

//! The keys of a level are the row numbers 0..n-1 of that level
static unique_ptr<BaseStatistics> ReadParquetNodeStatistics(ClientContext &context, const FunctionData *bind_data,
                                                            column_t column_index) {
	auto &data = bind_data->Cast<ReadParquetNodeData>();
	auto &node = data.node;
	const auto leaf_count = node.leaves.size();
	if (column_index < leaf_count || column_index >= leaf_count + node.level + 1) {
		return nullptr;
	}
	auto key_index = column_index - leaf_count;
	auto level = key_index == 0 ? node.level : key_index - 1;
	auto upper_bound = data.key_upper_bounds[level];
	if (upper_bound == 0) {
		return NumericStats::CreateEmpty(LogicalType::BIGINT).ToUnique();
	}
	auto stats = NumericStats::CreateUnknown(LogicalType::BIGINT);
	NumericStats::SetMin(stats, Value::BIGINT(0));
	NumericStats::SetMax(stats, Value::BIGINT(NumericCast<int64_t>(upper_bound - 1)));
	stats.SetHasNoNull();
	return stats.ToUnique();
}

static InsertionOrderPreservingMap<string> ReadParquetNodeToString(TableFunctionToStringInput &input) {
	InsertionOrderPreservingMap<string> result;
	if (input.bind_data) {
		auto &data = input.bind_data->Cast<ReadParquetNodeData>();
		result["File"] = data.reader->GetFileName();
		result["Node"] = data.node_path.empty() ? "(top level)" : data.node_path;
	}
	return result;
}

unique_ptr<LogicalGet> ReadParquetNodeFunction::CreateGet(ClientContext &context, TableIndex table_index,
                                                          const string &file, const string &node_path) {
	// bind the function the way the binder binds a call to it, so that the plan can be serialized and copied
	BoundTableFunction function(GetFunction());
	vector<Value> parameters {Value(file)};
	named_argument_map_t named_parameters;
	named_parameters["node"] = Value(node_path);
	function.GetSignature().FillNamedDefaults(context, named_parameters);
	function.SetCallArguments(parameters, named_parameters);
	vector<LogicalType> input_table_types;
	vector<Identifier> input_table_names;
	TableFunctionRef ref;
	TableFunctionBindInput bind_input(parameters, named_parameters, input_table_types, input_table_names,
	                                  function.function_info.get(), nullptr, function, ref);
	vector<LogicalType> return_types;
	vector<Identifier> names;
	auto bind_data = function.bind(context, bind_input, return_types, names);
	auto get = make_uniq<LogicalGet>(table_index, std::move(function), std::move(bind_data), std::move(return_types),
	                                 std::move(names));
	get->parameters = std::move(parameters);
	get->named_parameters = std::move(named_parameters);
	return get;
}

TableFunction ReadParquetNodeFunction::GetFunction() {
	TableFunction function("read_parquet_node", FunctionSignature().AddPositionalOnly("file", LogicalType::VARCHAR),
	                       ReadParquetNodeScan, ReadParquetNodeBind, ReadParquetNodeInitGlobal,
	                       ReadParquetNodeInitLocal);
	function.GetSignature()
	    .AddKeywordOnly("node", LogicalType::VARCHAR, Value(""))
	    .AddKeywordOnly("include_empty", LogicalType::BOOLEAN, Value::BOOLEAN(false));
	function.cardinality = ReadParquetNodeCardinality;
	function.statistics = ReadParquetNodeStatistics;
	function.get_partition_data = ReadParquetNodePartitionData;
	function.table_scan_progress = ReadParquetNodeProgress;
	function.to_string = ReadParquetNodeToString;
	function.projection_pushdown = true;
	return function;
}

} // namespace duckdb
