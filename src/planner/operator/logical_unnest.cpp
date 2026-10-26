#include "duckdb/planner/operator/logical_unnest.hpp"

#include "duckdb/main/config.hpp"

namespace duckdb {

vector<ColumnBinding> LogicalUnnest::GetColumnBindings() {
	auto child_bindings = children[0]->GetColumnBindings();
	for (auto unnest_col_idx : ProjectionIndex::GetIndexes(expressions.size())) {
		child_bindings.emplace_back(unnest_index, unnest_col_idx);
	}
	return child_bindings;
}

//! Revived from the version removed in fff6e6276e. Makes the absorbed comprehensions
//! visible in EXPLAIN, which is how they are counted - nothing consumes them yet.
InsertionOrderPreservingMap<string> LogicalUnnest::ParamsToString() const {
	auto result = LogicalOperator::ParamsToString();
	if (!filters.empty()) {
		string filters_info;
		for (idx_t i = 0; i < filters.size(); i++) {
			if (i > 0) {
				filters_info += "\n";
			}
			filters_info += filters[i]->GetName();
		}
		result["Comprehension Filters"] = filters_info;
	}
	return result;
}

void LogicalUnnest::ResolveTypes() {
	types.insert(types.end(), children[0]->types.begin(), children[0]->types.end());
	for (auto &expr : expressions) {
		types.push_back(expr->GetReturnType());
	}
}

vector<TableIndex> LogicalUnnest::GetTableIndex() const {
	return vector<TableIndex> {unnest_index};
}

string LogicalUnnest::GetName() const {
#ifdef DEBUG
	if (DBConfigOptions::debug_print_bindings) {
		return LogicalOperator::GetName() + StringUtil::Format(" #%llu", unnest_index.index);
	}
#endif
	return LogicalOperator::GetName();
}

} // namespace duckdb
