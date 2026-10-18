#include "parquet_nested_keys.hpp"

#include "column_reader.hpp"
#include "parquet_reader.hpp"
#include "duckdb/common/string_util.hpp"
#include "duckdb/common/types/data_chunk.hpp"
#include "duckdb/parallel/task_executor.hpp"
#include "duckdb/logging/logger.hpp"
#include "duckdb/main/client_context.hpp"
#include "duckdb/main/client_context_state.hpp"

#include <algorithm>

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

void ParquetNodeKeyGenerator::BeginTask(const vector<idx_t> &rows_before) {
	D_ASSERT(rows_before.size() == level + 1);
	// the current row of every level is the last one that started before the task: a slot that starts a new row
	// increments its key, a slot that continues a row (e.g. the first slot of the task) keeps it
	for (idx_t k = 0; k <= level; k++) {
		counters[k] = NumericCast<int64_t>(rows_before[k]) - 1;
	}
	task_rows_before = rows_before;
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
	return NumericCast<idx_t>(counters[key_level] + 1) - task_rows_before[key_level];
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

//! The pages of the column chunks of the files a query reads - shared by its scans, and dropped when it ends
class ParquetNodePageCache : public ClientContextState {
public:
	static constexpr const char *NAME = "parquet_node_page_cache";

	shared_ptr<ParquetColumnPages> Get(const ParquetReader &reader, idx_t row_group, idx_t column_index) {
		auto key = reader.GetFileName() + "|" + to_string(row_group) + "|" + to_string(column_index);
		lock_guard<mutex> guard(lock);
		auto &entry = entries[key];
		if (!entry) {
			entry = make_shared_ptr<ParquetColumnPages>();
		}
		return entry;
	}
	void QueryEnd() override {
		lock_guard<mutex> guard(lock);
		entries.clear();
	}

private:
	mutex lock;
	unordered_map<string, shared_ptr<ParquetColumnPages>> entries;
};

idx_t FindPageOfSlot(const vector<ColumnPageInfo> &pages, idx_t slot) {
	auto page = std::upper_bound(pages.begin(), pages.end(), slot,
	                             [](idx_t value, const ColumnPageInfo &info) { return value < info.first_value; });
	if (page == pages.begin()) {
		throw InternalException("read_parquet_node: no page holds slot %llu", slot);
	}
	return NumericCast<idx_t>(page - pages.begin()) - 1;
}

void ParquetNodeTask::KeyRange(idx_t key_level, idx_t key_upper_bound, idx_t &min_key, idx_t &max_key) const {
	auto before = rows_before[key_level];
	// a part can start within a row that started before it
	min_key = slot_start > 0 && before > 0 ? before - 1 : before;
	idx_t end = key_upper_bound;
	if (rows_in_task[key_level].IsValid()) {
		end = before + rows_in_task[key_level].GetIndex();
	}
	max_key = MaxValue<idx_t>(min_key, end > 0 ? end - 1 : 0);
}

//! A column reader positioned at the start of the column chunk of a row group
static unique_ptr<ColumnReader> OpenColumnChunk(const ParquetReader &reader, const ParquetColumnSchema &leaf,
                                                idx_t row_group, TProtocol &protocol) {
	auto &group = reader.GetFileMetadata()->row_groups[row_group];
	auto column_reader = ColumnReader::CreateReader(reader, leaf);
	column_reader->InitializeRead(row_group, NumericCast<idx_t>(group.num_rows), group.columns, protocol);
	return column_reader;
}

//! Reads the page headers of a column chunk
class ReadPageDirectoryTask : public BaseExecutorTask {
public:
	ReadPageDirectoryTask(TaskExecutor &executor, ClientContext &context, const ParquetReader &reader,
	                      const ParquetColumnSchema &leaf, idx_t row_group, ParquetColumnPages &pages)
	    : BaseExecutorTask(executor), context(context), reader(reader), leaf(leaf), row_group(row_group),
	      pages(pages) {
	}

	void ExecuteTask() override {
		lock_guard<mutex> guard(pages.lock);
		if (pages.directory_read) {
			return;
		}
		auto protocol = reader.OpenColumnProtocol(context);
		pages.pages = OpenColumnChunk(reader, leaf, row_group, *protocol)->ReadPageDirectory();
		pages.directory_read = true;
	}

	string TaskType() const override {
		return "ReadPageDirectoryTask";
	}

private:
	ClientContext &context;
	const ParquetReader &reader;
	const ParquetColumnSchema &leaf;
	idx_t row_group;
	ParquetColumnPages &pages;
};

//! Counts the slots of a page that start a row of each level - reading only their levels
class CountPageLevelRows : public BaseExecutorTask {
public:
	CountPageLevelRows(TaskExecutor &executor, ClientContext &context, const ParquetReader &reader,
	                   const ParquetColumnSchema &leaf, idx_t row_group, const ColumnPageInfo &page, idx_t slot_count,
	                   vector<idx_t> &result)
	    : BaseExecutorTask(executor), context(context), reader(reader), leaf(leaf), row_group(row_group), page(page),
	      slot_count(slot_count), result(result) {
	}

	void ExecuteTask() override {
		auto protocol = reader.OpenColumnProtocol(context);
		auto column_reader = OpenColumnChunk(reader, leaf, row_group, *protocol);
		column_reader->SeekToPage(page, false);
		ResizeableBuffer define_buf(reader.allocator, STANDARD_VECTOR_SIZE);
		ResizeableBuffer repeat_buf(reader.allocator, STANDARD_VECTOR_SIZE);
		auto defines = reinterpret_cast<uint8_t *>(define_buf.ptr);
		auto repeats = reinterpret_cast<uint8_t *>(repeat_buf.ptr);
		const auto max_level = result.size() - 1;
		auto slots_left = slot_count;
		while (slots_left > 0) {
			auto count = MinValue<idx_t>(STANDARD_VECTOR_SIZE, slots_left);
			memset(defines, 0, count);
			memset(repeats, 0, count);
			ColumnReaderInput input(count, defines, repeats);
			column_reader->ReadLevels(input);
			for (idx_t i = 0; i < count; i++) {
				// a slot repeated at level r starts a row on every level >= r
				for (idx_t k = repeats[i]; k <= max_level; k++) {
					result[k]++;
				}
			}
			slots_left -= count;
		}
	}

	string TaskType() const override {
		return "CountPageLevelRows";
	}

private:
	ClientContext &context;
	const ParquetReader &reader;
	const ParquetColumnSchema &leaf;
	idx_t row_group;
	const ColumnPageInfo &page;
	//! The slots at the start of the page that are counted
	idx_t slot_count;
	vector<idx_t> &result;
};

//! Count the rows of every level per page of a column chunk, once per query, the pages in parallel
static void CountLevelRowsPerPage(ClientContext &context, const ParquetReader &reader,
                                  const ParquetColumnSchema &leaf, idx_t row_group, ParquetColumnPages &pages) {
	lock_guard<mutex> guard(pages.lock);
	if (pages.levels_counted) {
		return;
	}
	pages.level_rows.assign(pages.pages.size(), vector<idx_t>(leaf.max_repeat + 1, 0));
	TaskExecutor executor(context);
	for (idx_t p = 0; p < pages.pages.size(); p++) {
		executor.ScheduleTask(make_uniq<CountPageLevelRows>(executor, context, reader, leaf, row_group, pages.pages[p],
		                                                    pages.pages[p].num_values, pages.level_rows[p]));
	}
	executor.WorkOnTasks();
	pages.levels_counted = true;
	DUCKDB_LOG_DEBUG(context, StringUtil::Format("read_parquet_node: counted the levels of %llu pages of column \"%s\" "
	                                             "in row group %llu of \"%s\"",
	                                             pages.pages.size(), leaf.name, row_group, reader.GetFileName()));
}

ParquetNodeTaskPlan ParquetNodeTaskPlan::Create(ClientContext &context, const ParquetReader &reader,
                                                const ParquetNodeInfo &node,
                                                const vector<reference<const ParquetColumnSchema>> &read_leaves,
                                                const vector<bool> &needed_levels, idx_t threads,
                                                idx_t min_task_slots) {
	auto &slot_leaf = read_leaves[0].get();
	auto rows = ParquetNodeRowGroupRows::Compute(context, reader, node);
	auto &row_groups = reader.GetFileMetadata()->row_groups;
	vector<idx_t> row_group_slots;
	idx_t total_slots = 0;
	for (auto &group : row_groups) {
		row_group_slots.push_back(NumericCast<idx_t>(group.columns[slot_leaf.column_index].meta_data.num_values));
		total_slots += row_group_slots.back();
	}
	// row groups are only split when they occupy at most half of the threads: splitting raises the parallelism of the
	// scan at most threads / row groups times, and below 2x that does not pay for counting the levels of every split
	// row group and decompressing the pages that parts start in again. Not either when there is too little to split
	auto task_slots = threads <= 1 || row_groups.size() * 2 > threads
	                      ? NumericLimits<idx_t>::Maximum()
	                      : MaxValue<idx_t>(MaxValue<idx_t>(min_task_slots, 1), total_slots / (threads * 4));

	ParquetNodeTaskPlan result;
	auto add_whole_row_group = [&](idx_t rg) {
		ParquetNodeTask task;
		task.row_group = rg;
		task.slot_end = row_group_slots[rg];
		task.rows_before = rows.offsets[rg];
		task.rows_in_task = rows.counts[rg];
		result.tasks.push_back(std::move(task));
	};
	vector<idx_t> split_candidates;
	for (idx_t rg = 0; rg < row_groups.size(); rg++) {
		if (row_group_slots[rg] > task_slots) {
			split_candidates.push_back(rg);
		}
	}
	if (split_candidates.empty()) {
		for (idx_t rg = 0; rg < row_groups.size(); rg++) {
			add_whole_row_group(rg);
		}
		return result;
	}

	// every slot of a column directly in the node starts one of its rows (or a placeholder). These columns have the
	// same levels, so a part can start at the pages of any of them: at those of a large column that is read, whose
	// pages are then decompressed only once - or within its pages, when it has fewer pages than parts. The rows before
	// a part are counted per page of a cheap column of the node - with a page for every part, so that the pages are
	// counted in parallel and a part starts in a small page
	const bool slots_are_rows = !node.leaves.empty();
	vector<idx_t> counted_levels;
	for (idx_t k = 0; k <= node.level; k++) {
		if (needed_levels[k] && !(slots_are_rows && k == node.level)) {
			counted_levels.push_back(k);
		}
	}
	vector<reference<const ParquetColumnSchema>> count_candidates;
	if (slots_are_rows) {
		for (auto &leaf : node.leaves) {
			count_candidates.push_back(*leaf.schema);
		}
	} else {
		count_candidates.push_back(slot_leaf);
	}
	auto compressed_size = [&](idx_t rg, const ParquetColumnSchema &leaf) {
		return NumericCast<idx_t>(row_groups[rg].columns[leaf.column_index].meta_data.total_compressed_size);
	};
	auto &cache = *context.registered_state->GetOrCreate<ParquetNodePageCache>(ParquetNodePageCache::NAME);
	{
		TaskExecutor executor(context);
		for (auto rg : split_candidates) {
			auto schedule = [&](const ParquetColumnSchema &leaf) {
				auto pages = cache.Get(reader, rg, leaf.column_index);
				executor.ScheduleTask(make_uniq<ReadPageDirectoryTask>(executor, context, reader, leaf, rg, *pages));
			};
			for (auto &leaf : read_leaves) {
				schedule(leaf.get());
			}
			if (!counted_levels.empty()) {
				for (auto &leaf : count_candidates) {
					schedule(leaf.get());
				}
			}
		}
		executor.WorkOnTasks();
	}

	idx_t next_candidate = 0;
	for (idx_t rg = 0; rg < row_groups.size(); rg++) {
		if (next_candidate >= split_candidates.size() || split_candidates[next_candidate] != rg) {
			add_whole_row_group(rg);
			continue;
		}
		next_candidate++;
		auto page_count = [&](const ParquetColumnSchema &leaf) {
			return cache.Get(reader, rg, leaf.column_index)->pages.size();
		};
		// about one part per thread
		auto wanted_parts = MinValue<idx_t>(threads, row_group_slots[rg] / task_slots);
		if (wanted_parts < 2) {
			add_whole_row_group(rg);
			continue;
		}
		// the largest column that is read and has a page for every part - or else the one with the most pages
		optional_ptr<const ParquetColumnSchema> boundary_leaf;
		string page_counts;
		for (auto &leaf : read_leaves) {
			page_counts += StringUtil::Format("%s%s: %llu", page_counts.empty() ? "" : ", ", leaf.get().name,
			                                  page_count(leaf.get()));
			if (!boundary_leaf) {
				boundary_leaf = leaf.get();
				continue;
			}
			bool enough = page_count(leaf.get()) >= wanted_parts;
			bool boundary_enough = page_count(*boundary_leaf) >= wanted_parts;
			bool better;
			if (enough != boundary_enough) {
				better = enough;
			} else if (enough) {
				better = compressed_size(rg, leaf.get()) > compressed_size(rg, *boundary_leaf);
			} else {
				better = page_count(leaf.get()) > page_count(*boundary_leaf);
			}
			if (better) {
				boundary_leaf = leaf.get();
			}
		}
		auto boundary_pages = cache.Get(reader, rg, boundary_leaf->column_index);
		auto &pages = boundary_pages->pages;
		vector<idx_t> slot_starts {0};
		const bool within_pages = pages.size() < wanted_parts;
		if (within_pages) {
			// fewer pages than parts: the parts start at offsets within the pages as well, so that every thread has a
			// part - the pages a part starts in are then decompressed by more than one part
			for (idx_t i = 1; i < wanted_parts; i++) {
				slot_starts.push_back(row_group_slots[rg] * i / wanted_parts);
			}
		} else {
			auto part_slots = MaxValue<idx_t>(task_slots, row_group_slots[rg] / wanted_parts);
			for (idx_t p = 1; p < pages.size(); p++) {
				if (pages[p].first_value - slot_starts.back() >= part_slots) {
					slot_starts.push_back(pages[p].first_value);
				}
			}
		}
		if (slot_starts.size() == 1) {
			add_whole_row_group(rg);
			continue;
		}
		slot_starts.push_back(row_group_slots[rg]);
		const auto part_count = slot_starts.size() - 1;

		// the rows of the counted levels before every part: those of the pages of the count column before it, and of
		// the slots of the page it starts in
		vector<vector<idx_t>> rows_at_start(slot_starts.size(), vector<idx_t>(node.level + 1, 0));
		optional_ptr<const ParquetColumnSchema> count_leaf;
		if (!counted_levels.empty()) {
			// the cheapest column with a page for every part - or else the column of the boundaries
			for (auto &leaf : count_candidates) {
				if (page_count(leaf.get()) >= part_count &&
				    (!count_leaf || compressed_size(rg, leaf.get()) < compressed_size(rg, *count_leaf))) {
					count_leaf = leaf.get();
				}
			}
			if (!count_leaf) {
				count_leaf = boundary_leaf;
			}
			auto count_pages = cache.Get(reader, rg, count_leaf->column_index);
			CountLevelRowsPerPage(context, reader, *count_leaf, rg, *count_pages);
			auto &cpages = count_pages->pages;
			vector<vector<idx_t>> partial(slot_starts.size(), vector<idx_t>(count_leaf->max_repeat + 1, 0));
			vector<idx_t> start_page(slot_starts.size(), cpages.size());
			TaskExecutor executor(context);
			for (idx_t i = 0; i < part_count; i++) {
				start_page[i] = FindPageOfSlot(cpages, slot_starts[i]);
				auto &page = cpages[start_page[i]];
				if (slot_starts[i] > page.first_value) {
					executor.ScheduleTask(make_uniq<CountPageLevelRows>(executor, context, reader, *count_leaf, rg,
					                                                    page, slot_starts[i] - page.first_value,
					                                                    partial[i]));
				}
			}
			executor.WorkOnTasks();
			for (auto k : counted_levels) {
				for (idx_t i = 0; i < slot_starts.size(); i++) {
					idx_t before = 0;
					for (idx_t p = 0; p < start_page[i]; p++) {
						before += count_pages->level_rows[p][k];
					}
					rows_at_start[i][k] = before + partial[i][k];
				}
				// the rows of the row group: those of all pages
				if (rows.counts[rg][k].IsValid() && rows_at_start.back()[k] != rows.counts[rg][k].GetIndex()) {
					throw InvalidInputException("read_parquet_node: corrupt file \"%s\": row group %llu has %llu rows "
					                            "on nesting level %llu according to its repetition levels, but %llu "
					                            "according to its metadata",
					                            reader.GetFileName(), rg, rows_at_start.back()[k], k,
					                            rows.counts[rg][k].GetIndex());
				}
			}
		}
		vector<shared_ptr<ParquetColumnPages>> leaf_pages;
		for (auto &leaf : read_leaves) {
			leaf_pages.push_back(cache.Get(reader, rg, leaf.get().column_index));
		}
		for (idx_t i = 0; i + 1 < slot_starts.size(); i++) {
			ParquetNodeTask task;
			task.row_group = rg;
			task.slot_start = slot_starts[i];
			task.slot_end = slot_starts[i + 1];
			task.rows_before.resize(node.level + 1, 0);
			task.rows_in_task.resize(node.level + 1);
			task.leaf_pages = leaf_pages;
			if (slots_are_rows) {
				task.rows_before[node.level] = rows.offsets[rg][node.level] + task.slot_start;
				task.rows_in_task[node.level] = task.slot_end - task.slot_start;
			}
			for (auto k : counted_levels) {
				task.rows_before[k] = rows.offsets[rg][k] + rows_at_start[i][k];
				task.rows_in_task[k] = rows_at_start[i + 1][k] - rows_at_start[i][k];
			}
			result.tasks.push_back(std::move(task));
		}
		string counting;
		if (count_leaf) {
			counting = StringUtil::Format(", counting levels in column \"%s\" (%llu pages)", count_leaf->name,
			                              page_count(*count_leaf));
		}
		DUCKDB_LOG_DEBUG(context, StringUtil::Format("read_parquet_node: row group %llu of \"%s\" is scanned in %llu "
		                                             "parts, %s the pages of column \"%s\" (pages: %s)%s",
		                                             rg, reader.GetFileName(), part_count,
		                                             within_pages ? "within" : "at", boundary_leaf->name, page_counts,
		                                             counting));
	}
	return result;
}

} // namespace duckdb
