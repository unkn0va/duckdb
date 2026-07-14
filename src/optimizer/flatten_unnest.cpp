#include "duckdb/optimizer/flatten_unnest.hpp"

#include "duckdb/common/types.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/planner/operator/logical_unnest.hpp"
#include "duckdb/planner/expression/bound_unnest_expression.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_function_expression.hpp"

#include <algorithm>

namespace duckdb {

void FlattenUnnest::RewriteUnnests(LogicalOperator &op) {
	// children first: rewrite the deepest UNNEST/GET pairs before their parents
	for (auto &child : op.children) {
		RewriteUnnests(*child);
	}
	if (op.type != LogicalOperatorType::LOGICAL_UNNEST) {
		return;
	}
	auto &unnest = op.Cast<LogicalUnnest>();

	// Find the LogicalGet directly below this UNNEST (through projections only). Bail if another UNNEST
	// intervenes: that is the multi-level case, which needs the collapse reader (future increment).
	LogicalOperator *cur = op.children.empty() ? nullptr : op.children[0].get();
	while (cur) {
		if (cur->type == LogicalOperatorType::LOGICAL_GET) {
			break;
		}
		if (cur->type == LogicalOperatorType::LOGICAL_UNNEST) {
			return;
		}
		if (cur->children.empty()) {
			return;
		}
		cur = cur->children[0].get();
	}
	if (!cur || cur->type != LogicalOperatorType::LOGICAL_GET) {
		return;
	}
	auto &get = cur->Cast<LogicalGet>();
	if (get.flatten_columns.empty()) {
		return;
	}
	auto &col_ids = get.GetMutableColumnIds();

	for (idx_t i = 0; i < unnest.expressions.size(); i++) {
		auto &expr = unnest.expressions[i];
		if (expr->GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
			continue;
		}
		auto &bu = expr->Cast<BoundUnnestExpression>();
		if (bu.child->GetExpressionClass() != ExpressionClass::BOUND_COLUMN_REF) {
			continue;
		}
		auto &cref = bu.child->Cast<BoundColumnRefExpression>();
		idx_t logical_idx = cref.binding.column_index;
		if (logical_idx >= col_ids.size()) {
			continue;
		}
		idx_t phys = col_ids[logical_idx].GetPrimaryIndex();
		if (std::find(get.flatten_columns.begin(), get.flatten_columns.end(), phys) == get.flatten_columns.end()) {
			continue;
		}
		// prototype: single leaf sub-field only
		auto np = get.nested_projection_map.find(phys);
		if (np == get.nested_projection_map.end() || np->second.size() != 1) {
			continue;
		}
		idx_t leaf_idx = np->second[0];

		// current column type is LIST<STRUCT<...>>; compute the leaf type
		auto &col_type = cref.return_type;
		if (col_type.id() != LogicalTypeId::LIST) {
			continue;
		}
		auto &elem = ListType::GetChildType(col_type);
		if (elem.id() != LogicalTypeId::STRUCT) {
			continue;
		}
		auto &struct_children = StructType::GetChildTypes(elem);
		if (leaf_idx >= struct_children.size()) {
			continue;
		}
		auto leaf_type = struct_children[leaf_idx].second;
		// Prototype: single nesting level with a SCALAR leaf. A nested "leaf" (e.g. c_orders.o_lineitems is a
		// LIST) is the multi-level case handled by the collapse reader later; skip it here so reader and plan
		// stay consistent (the reader hook applies the same guard).
		if (leaf_type.IsNested()) {
			continue;
		}
		auto new_list_type = LogicalType::LIST(leaf_type);

		// (1) the scan now produces LIST<leaf> for this column (matches the collapse reader)
		col_ids[logical_idx].SetType(new_list_type);
		// (2) the UNNEST input is LIST<leaf>, its output is the leaf scalar
		cref.return_type = new_list_type;
		bu.return_type = leaf_type;
		// (3) record the unnest output so the struct_extract above it can be dropped in phase 2
		flattened_outputs[ColumnBinding(unnest.unnest_index, i)] = leaf_type;
	}
}

unique_ptr<Expression> FlattenUnnest::VisitReplace(BoundFunctionExpression &expr, unique_ptr<Expression> *expr_ptr) {
	if ((expr.function.name == "struct_extract" || expr.function.name == "struct_extract_at") &&
	    !expr.children.empty() && expr.children[0]->GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
		auto &cref = expr.children[0]->Cast<BoundColumnRefExpression>();
		auto entry = flattened_outputs.find(cref.binding);
		if (entry != flattened_outputs.end()) {
			// the unnest output is now the leaf scalar itself: drop the extract, keep a plain column ref
			return make_uniq<BoundColumnRefExpression>(expr.GetAlias(), entry->second, cref.binding);
		}
	}
	// no replacement here: the base visitor recurses into children automatically on a null return
	return nullptr;
}

unique_ptr<LogicalOperator> FlattenUnnest::Optimize(unique_ptr<LogicalOperator> op) {
	RewriteUnnests(*op);
	if (!flattened_outputs.empty()) {
		// phase 2: drop struct_extract on the flattened unnest outputs
		VisitOperator(*op);
		// types of GET/UNNEST/projection changed: re-resolve the whole tree
		op->ResolveOperatorTypes();
	}
	return op;
}

} // namespace duckdb
