#include "parquet_nested_keys.hpp"

#include "parquet_reader.hpp"
#include "duckdb/main/config.hpp"
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/optimizer/optimizer_extension.hpp"
#include "duckdb/optimizer/remove_unused_columns.hpp"
#include "duckdb/planner/binder.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/operator/logical_comparison_join.hpp"
#include "duckdb/planner/operator/logical_projection.hpp"

namespace duckdb {

struct ReadParquetFlatData : public TableFunctionData {
	string file;
	//! The nodes of the file in preorder - the first one is the top level
	vector<ParquetFlatNode> nodes;
	//! The node and the column within the node of every column of the scan
	vector<pair<idx_t, idx_t>> columns;
};

static unique_ptr<FunctionData> ReadParquetFlatBind(ClientContext &context, TableFunctionBindInput &input,
                                                    vector<LogicalType> &return_types, vector<Identifier> &names) {
	if (input.inputs[0].IsNull()) {
		throw BinderException("read_parquet_flat requires a non-NULL file name");
	}
	auto result = make_uniq<ReadParquetFlatData>();
	result->file = input.inputs[0].GetValue<string>();
	ParquetReader reader(context, OpenFileInfo(result->file), ParquetOptions(context));
	result->nodes = ParquetFlatNode::EnumerateNodes(*reader.root_schema);

	case_insensitive_set_t column_names;
	for (idx_t node_idx = 0; node_idx < result->nodes.size(); node_idx++) {
		auto &node = result->nodes[node_idx];
		for (idx_t leaf_idx = 0; leaf_idx < node.column_names.size(); leaf_idx++) {
			auto &name = node.column_names[leaf_idx];
			if (!column_names.insert(name).second) {
				throw BinderException("read_parquet_flat: the file \"%s\" has several columns with the path \"%s\"",
				                      result->file, name);
			}
			names.emplace_back(name);
			return_types.push_back(node.leaf_types[leaf_idx]);
			result->columns.emplace_back(node_idx, leaf_idx);
		}
	}
	if (names.empty()) {
		throw BinderException("read_parquet_flat: the file \"%s\" has no columns that can be read", result->file);
	}
	return std::move(result);
}

static virtual_column_map_t ReadParquetFlatVirtualColumns(ClientContext &context,
                                                          optional_ptr<FunctionData> bind_data) {
	// without a column of its own for count(*), any column - and so any node - could be scanned for it
	virtual_column_map_t result;
	result.insert(make_pair(COLUMN_IDENTIFIER_EMPTY, TableColumn("", LogicalType::BOOLEAN)));
	return result;
}

static unique_ptr<GlobalTableFunctionState> ReadParquetFlatInitGlobal(ClientContext &context,
                                                                      TableFunctionInitInput &input) {
	throw InvalidInputException("read_parquet_flat is replaced by scans of the nodes of the file while the query is "
	                            "optimized - it cannot be used with the optimizer (or its extensions) disabled");
}

static void ReadParquetFlatScan(ClientContext &context, TableFunctionInput &input, DataChunk &output) {
	throw InternalException("read_parquet_flat was not replaced by scans of its nodes");
}

//! The node at the given level on the path from the top level to a node
static idx_t AncestorAtLevel(const vector<ParquetFlatNode> &nodes, idx_t node_idx, idx_t level) {
	while (nodes[node_idx].level > level) {
		node_idx = nodes[node_idx].parent.GetIndex();
	}
	return node_idx;
}

static idx_t LowestCommonAncestor(const vector<ParquetFlatNode> &nodes, idx_t a, idx_t b) {
	auto level = MinValue(nodes[a].level, nodes[b].level);
	a = AncestorAtLevel(nodes, a, level);
	b = AncestorAtLevel(nodes, b, level);
	while (a != b) {
		a = nodes[a].parent.GetIndex();
		b = nodes[b].parent.GetIndex();
	}
	return a;
}

//! A scan of a node, and where the columns that are needed of it are in its column ids
struct FlatNodeScan {
	unique_ptr<LogicalGet> get;
	unordered_map<idx_t, ProjectionIndex> leaf_positions;
	unordered_map<idx_t, ProjectionIndex> key_positions;
};

//! An equality between the keys of a level of two nodes
struct FlatNodeJoin {
	idx_t left_node;
	idx_t right_node;
	idx_t level;
};

static ProjectionIndex AddKey(const ParquetFlatNode &node, FlatNodeScan &scan, idx_t level) {
	auto entry = scan.key_positions.find(level);
	if (entry != scan.key_positions.end()) {
		return entry->second;
	}
	// read_parquet_node returns the columns of the node, the surrogate key and the ancestor keys of levels 0, 1, ...
	const auto leaf_count = node.leaf_names.size();
	auto column_id = level == node.level ? leaf_count : leaf_count + 1 + level;
	auto position = scan.get->AddColumnId(column_id);
	scan.key_positions.emplace(level, position);
	return position;
}

static unique_ptr<Expression> KeyReference(const ParquetFlatNode &node, FlatNodeScan &scan, idx_t level) {
	auto position = AddKey(node, scan, level);
	auto name = level == node.level ? "_sk" : "_ak" + to_string(level);
	return make_uniq<BoundColumnRefExpression>(Identifier(name), LogicalType::BIGINT,
	                                           ColumnBinding(scan.get->table_index, position));
}

//! The columns of the read_parquet_flat scans that the plan uses, by the table index of the scan
using FlatScanUsedColumns = unordered_map<TableIndex, unordered_set<column_t>>;

//! Replace a scan of read_parquet_flat by the scans of the nodes of its columns, joined on their keys. Only the nodes
//! of the used columns are scanned - the other referenced columns are not used and are replaced by NULL
static unique_ptr<LogicalOperator> RewriteFlatScan(ClientContext &context, Optimizer &optimizer, LogicalGet &get,
                                                   optional_ptr<const FlatScanUsedColumns> used_columns) {
	auto &data = get.bind_data->Cast<ReadParquetFlatData>();
	auto &nodes = data.nodes;
	if (!get.projection_ids.empty() || get.table_filters.HasFilters() || get.ordinality_idx.IsValid()) {
		throw InternalException("read_parquet_flat: the scan was modified before it could be replaced");
	}
	auto &column_ids = get.GetColumnIds();
	optional_ptr<const unordered_set<column_t>> used;
	if (used_columns) {
		auto entry = used_columns->find(get.table_index);
		if (entry != used_columns->end()) {
			used = entry->second;
		}
	}
	auto is_used = [&](column_t column_id) {
		return column_id != COLUMN_IDENTIFIER_EMPTY && (!used || used->find(column_id) != used->end());
	};

	// the nodes of the used columns - only the top level if no column is used
	vector<bool> required(nodes.size(), false);
	for (auto &column_index : column_ids) {
		if (column_index.HasChildren()) {
			throw InternalException("read_parquet_flat: nested column references cannot be replaced");
		}
		auto column_id = column_index.GetPrimaryIndex();
		if (column_id != COLUMN_IDENTIFIER_EMPTY && column_id >= data.columns.size()) {
			throw InternalException("read_parquet_flat: unsupported column %llu", column_id);
		}
		if (is_used(column_id)) {
			required[data.columns[column_id].first] = true;
		}
	}
	vector<idx_t> order;
	for (idx_t node_idx = 0; node_idx < nodes.size(); node_idx++) {
		if (required[node_idx]) {
			order.push_back(node_idx);
		}
	}
	if (order.empty()) {
		order.push_back(0);
	}

	// connect every node (in preorder) to the node before it with which it shares the deepest common ancestor -
	// their keys at the level of that ancestor are equal. The ancestors of all other pairs are then equal as well
	vector<FlatNodeJoin> joins;
	for (idx_t i = 1; i < order.size(); i++) {
		auto node_idx = order[i];
		optional_idx best_node;
		idx_t best_level = 0;
		bool best_is_ancestor = false;
		for (idx_t j = 0; j < i; j++) {
			auto ancestor = LowestCommonAncestor(nodes, order[j], node_idx);
			auto level = nodes[ancestor].level;
			auto is_ancestor = ancestor == order[j];
			// on a tie, prefer an ancestor of the node - that join is between a surrogate key and its references
			if (!best_node.IsValid() || level > best_level ||
			    (level == best_level && is_ancestor && !best_is_ancestor)) {
				best_node = order[j];
				best_level = level;
				best_is_ancestor = is_ancestor;
			}
		}
		joins.push_back({best_node.GetIndex(), node_idx, best_level});
	}

	// scan the referenced columns of every node, and the keys it is joined on
	unordered_map<idx_t, FlatNodeScan> scans;
	for (auto node_idx : order) {
		auto &scan = scans[node_idx];
		scan.get = ReadParquetNodeFunction::CreateGet(context, optimizer.binder.GenerateTableIndex(), data.file,
		                                              nodes[node_idx].path);
	}
	vector<unique_ptr<Expression>> select_list;
	for (auto &column_index : column_ids) {
		auto column_id = column_index.GetPrimaryIndex();
		if (column_id == COLUMN_IDENTIFIER_EMPTY) {
			select_list.push_back(make_uniq<BoundConstantExpression>(Value(LogicalType::BOOLEAN)));
			continue;
		}
		auto &column = data.columns[column_id];
		if (!is_used(column_id)) {
			auto &type = nodes[column.first].leaf_types[column.second];
			select_list.push_back(make_uniq<BoundConstantExpression>(Value(type)));
			continue;
		}
		auto &node = nodes[column.first];
		auto &scan = scans[column.first];
		auto entry = scan.leaf_positions.find(column.second);
		if (entry == scan.leaf_positions.end()) {
			entry = scan.leaf_positions.emplace(column.second, scan.get->AddColumnId(column.second)).first;
		}
		auto position = entry->second;
		select_list.push_back(make_uniq<BoundColumnRefExpression>(Identifier(node.column_names[column.second]),
		                                                          node.leaf_types[column.second],
		                                                          ColumnBinding(scan.get->table_index, position)));
	}
	if (select_list.empty()) {
		// the scan produces a single column that nothing refers to (e.g. for count(*))
		select_list.push_back(make_uniq<BoundConstantExpression>(Value(LogicalType::BOOLEAN)));
	}

	// the keys are added to the scans before the scans are moved into the joins
	vector<JoinCondition> conditions;
	for (auto &join : joins) {
		auto left_key = KeyReference(nodes[join.left_node], scans[join.left_node], join.level);
		auto right_key = KeyReference(nodes[join.right_node], scans[join.right_node], join.level);
		conditions.emplace_back(std::move(left_key), std::move(right_key), ExpressionType::COMPARE_EQUAL);
	}
	// a left-deep tree of inner joins - the join order optimizer reorders it
	unique_ptr<LogicalOperator> plan = std::move(scans[order[0]].get);
	for (idx_t i = 0; i < joins.size(); i++) {
		auto comparison_join = make_uniq<LogicalComparisonJoin>(JoinType::INNER);
		comparison_join->children.push_back(std::move(plan));
		comparison_join->children.push_back(std::move(scans[joins[i].right_node].get));
		comparison_join->conditions.push_back(std::move(conditions[i]));
		plan = std::move(comparison_join);
	}

	// the projection keeps the table index of the replaced scan, so that the references to its columns stay valid
	auto projection = make_uniq<LogicalProjection>(get.table_index, std::move(select_list));
	projection->children.push_back(std::move(plan));
	projection->ResolveOperatorTypes();
	return std::move(projection);
}

static bool IsFlatScan(LogicalOperator &op) {
	return op.type == LogicalOperatorType::LOGICAL_GET &&
	       op.Cast<LogicalGet>().function.bind == ReadParquetFlatBind;
}

static void CollectFlatScans(LogicalOperator &op, vector<reference<LogicalGet>> &result) {
	for (auto &child : op.children) {
		CollectFlatScans(*child, result);
	}
	if (IsFlatScan(op)) {
		result.push_back(op.Cast<LogicalGet>());
	}
}

static void RewriteFlatScans(ClientContext &context, Optimizer &optimizer, unique_ptr<LogicalOperator> &op,
                             optional_ptr<const FlatScanUsedColumns> used_columns) {
	for (auto &child : op->children) {
		RewriteFlatScans(context, optimizer, child, used_columns);
	}
	if (IsFlatScan(*op)) {
		op = RewriteFlatScan(context, optimizer, op->Cast<LogicalGet>(), used_columns);
	}
}

//! The columns of the flat scans the plan uses - a column the binder bound (e.g. for "SELECT *" in a view) is not
//! necessarily used, and scanning its node would change the result. Determined by removing the unused columns from
//! a copy of the plan
static bool FindUsedColumns(OptimizerExtensionInput &input, LogicalOperator &plan, FlatScanUsedColumns &result) {
	unique_ptr<LogicalOperator> copy;
	try {
		copy = plan.Copy(input.context);
	} catch (std::exception &) {
		// the plan cannot be copied - every bound column is treated as used
		return false;
	}
	RemoveUnusedColumns unused_columns(input.optimizer);
	unused_columns.VisitOperator(copy);
	vector<reference<LogicalGet>> flat_scans;
	CollectFlatScans(*copy, flat_scans);
	for (auto &flat_scan : flat_scans) {
		auto &used = result[flat_scan.get().table_index];
		for (auto &column_index : flat_scan.get().GetColumnIds()) {
			used.insert(column_index.GetPrimaryIndex());
		}
	}
	return true;
}

static void ReadParquetFlatPreOptimize(OptimizerExtensionInput &input, unique_ptr<LogicalOperator> &plan) {
	vector<reference<LogicalGet>> flat_scans;
	CollectFlatScans(*plan, flat_scans);
	if (flat_scans.empty()) {
		return;
	}
	FlatScanUsedColumns used_columns;
	auto found = FindUsedColumns(input, *plan, used_columns);
	RewriteFlatScans(input.context, input.optimizer, plan, found ? &used_columns : nullptr);
}

TableFunction ReadParquetFlatFunction::GetFunction() {
	TableFunction function("read_parquet_flat", FunctionSignature().AddPositionalOnly("file", LogicalType::VARCHAR),
	                       ReadParquetFlatScan, ReadParquetFlatBind, ReadParquetFlatInitGlobal);
	function.get_virtual_columns = ReadParquetFlatVirtualColumns;
	function.projection_pushdown = true;
	return function;
}

void ReadParquetFlatFunction::RegisterOptimizer(DBConfig &config) {
	OptimizerExtension extension;
	extension.pre_optimize_function = ReadParquetFlatPreOptimize;
	OptimizerExtension::Register(config, std::move(extension));
}

} // namespace duckdb
