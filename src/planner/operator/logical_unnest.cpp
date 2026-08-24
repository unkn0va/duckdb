#include "duckdb/planner/operator/logical_unnest.hpp"

#include "duckdb/main/config.hpp"

namespace duckdb {

vector<ColumnBinding> LogicalUnnest::GetColumnBindings() {
	auto child_bindings = children[0]->GetColumnBindings();
	for (idx_t i = 0; i < expressions.size(); i++) {
		child_bindings.emplace_back(unnest_index, i);
	}
	return child_bindings;
}

InsertionOrderPreservingMap<string> LogicalUnnest::ParamsToString() const {
	auto result = LogicalOperator::ParamsToString();
	if (!element_filters.empty()) {
		string filters_info;
		for (idx_t i = 0; i < element_filters.size(); i++) {
			if (i > 0) {
				filters_info += "\n";
			}
			filters_info += element_filters[i]->GetName();
		}
		result["Element Filters"] = filters_info;
	}
	return result;
}

void LogicalUnnest::ResolveTypes() {
	types.insert(types.end(), children[0]->types.begin(), children[0]->types.end());
	for (auto &expr : expressions) {
		types.push_back(expr->return_type);
	}
}

vector<idx_t> LogicalUnnest::GetTableIndex() const {
	return vector<idx_t> {unnest_index};
}

string LogicalUnnest::GetName() const {
#ifdef DEBUG
	if (DBConfigOptions::debug_print_bindings) {
		return LogicalOperator::GetName() + StringUtil::Format(" #%llu", unnest_index);
	}
#endif
	return LogicalOperator::GetName();
}

} // namespace duckdb
