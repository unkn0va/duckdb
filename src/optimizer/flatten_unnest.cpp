#include "duckdb/optimizer/flatten_unnest.hpp"

#include "duckdb/common/types.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/planner/operator/logical_unnest.hpp"
#include "duckdb/planner/operator/logical_projection.hpp"
#include "duckdb/planner/expression/bound_unnest_expression.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_function_expression.hpp"
#include "duckdb/function/scalar/struct_utils.hpp"
#include "duckdb/planner/expression_iterator.hpp"

#include <algorithm>

namespace duckdb {

//! Return the struct-field index a struct_extract/struct_extract_at BoundFunctionExpression resolves to,
//! or optional_idx() if this is not a (bind-resolved) struct extract.
static optional_idx GetStructExtractIndex(const Expression &expr) {
	if (expr.GetExpressionClass() != ExpressionClass::BOUND_FUNCTION) {
		return optional_idx();
	}
	auto &func = expr.Cast<BoundFunctionExpression>();
	if (func.function.name != "struct_extract" && func.function.name != "struct_extract_at") {
		return optional_idx();
	}
	if (!func.bind_info) {
		return optional_idx();
	}
	return optional_idx(func.bind_info->Cast<StructExtractBindData>().index);
}

// ---------------------------------------------------------------------------------------------------------
// Phase 0: collect, for every column binding, the struct-field indices extracted from it (struct_extract).
// ---------------------------------------------------------------------------------------------------------
void FlattenUnnest::CollectExtractUses(Expression &expr) {
	auto idx = GetStructExtractIndex(expr);
	if (idx.IsValid()) {
		auto &func = expr.Cast<BoundFunctionExpression>();
		if (func.children[0]->GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
			auto &cref = func.children[0]->Cast<BoundColumnRefExpression>();
			extract_uses[cref.binding].push_back(idx.GetIndex());
		}
	}
	ExpressionIterator::EnumerateChildren(expr, [&](Expression &child) { CollectExtractUses(child); });
}

void FlattenUnnest::CollectOperator(LogicalOperator &op) {
	LogicalOperatorVisitor::EnumerateExpressions(op, [&](unique_ptr<Expression> *child) { CollectExtractUses(**child); });
	for (auto &c : op.children) {
		CollectOperator(*c);
	}
}

// ---------------------------------------------------------------------------------------------------------
// 2-level pattern: UNNEST_B(colref ol) over PROJECTION(ol = struct_extract(colref(A_out), list_field))
//                  over UNNEST_A(colref c_orders) over GET. Flatten GET.c_orders -> LIST<leaf> and collapse
//                  the two UNNESTs into the single UNNEST_B directly over GET.
// Returns true if the rewrite was applied.
// ---------------------------------------------------------------------------------------------------------
bool FlattenUnnest::TryFlattenTwoLevel(LogicalUnnest &outer) {
	if (outer.children.empty() || outer.children[0]->type != LogicalOperatorType::LOGICAL_PROJECTION) {
		return false;
	}
	auto &mid_proj = outer.children[0]->Cast<LogicalProjection>();
	if (mid_proj.children.empty() || mid_proj.children[0]->type != LogicalOperatorType::LOGICAL_UNNEST) {
		return false;
	}
	auto &inner = mid_proj.children[0]->Cast<LogicalUnnest>();
	if (inner.children.empty() || inner.children[0]->type != LogicalOperatorType::LOGICAL_GET) {
		return false; // prototype: inner UNNEST directly over GET
	}
	auto &get = inner.children[0]->Cast<LogicalGet>();
	if (get.flatten_columns.empty() || inner.expressions.size() != 1) {
		return false;
	}
	// inner unnest must unnest a plain GET column reference (c_orders)
	auto &bu_inner = inner.expressions[0];
	if (bu_inner->GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
		return false;
	}
	auto &inner_child = bu_inner->Cast<BoundUnnestExpression>().child;
	if (inner_child->GetExpressionClass() != ExpressionClass::BOUND_COLUMN_REF) {
		return false;
	}
	auto &c_orders_ref = inner_child->Cast<BoundColumnRefExpression>();
	idx_t c_orders_logical = c_orders_ref.binding.column_index;
	auto &col_ids = get.GetMutableColumnIds();
	if (c_orders_logical >= col_ids.size()) {
		return false;
	}
	idx_t phys = col_ids[c_orders_logical].GetPrimaryIndex();
	if (std::find(get.flatten_columns.begin(), get.flatten_columns.end(), phys) == get.flatten_columns.end()) {
		return false;
	}

	// process each expression of the outer unnest (prototype: single-leaf, expect one)
	for (idx_t i = 0; i < outer.expressions.size(); i++) {
		if (outer.expressions[i]->GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
			continue;
		}
		auto &bu_outer = outer.expressions[i]->Cast<BoundUnnestExpression>();
		if (bu_outer.child->GetExpressionClass() != ExpressionClass::BOUND_COLUMN_REF) {
			continue;
		}
		auto &ol_ref = bu_outer.child->Cast<BoundColumnRefExpression>();
		// ol must be defined by mid_proj as struct_extract(colref(inner_out), list_field)
		if (ol_ref.binding.table_index != mid_proj.table_index ||
		    ol_ref.binding.column_index >= mid_proj.expressions.size()) {
			continue;
		}
		auto &ol_def = *mid_proj.expressions[ol_ref.binding.column_index];
		auto list_field = GetStructExtractIndex(ol_def);
		if (!list_field.IsValid()) {
			continue;
		}
		auto &ol_extract = ol_def.Cast<BoundFunctionExpression>();
		if (ol_extract.children[0]->GetExpressionClass() != ExpressionClass::BOUND_COLUMN_REF) {
			continue;
		}
		auto &inner_out_ref = ol_extract.children[0]->Cast<BoundColumnRefExpression>();
		if (inner_out_ref.binding.table_index != inner.unnest_index) {
			continue; // the extracted column must be the inner unnest's output
		}
		// leaf field(s) used on the outer unnest output; prototype: exactly one (single-leaf)
		auto uses = extract_uses.find(ColumnBinding(outer.unnest_index, i));
		if (uses == extract_uses.end() || uses->second.size() != 1) {
			continue;
		}
		idx_t leaf_field = uses->second[0];

		// compute the leaf type: c_orders is LIST<STRUCT<order>>; .list_field is LIST<STRUCT<lineitem>>;
		// .leaf_field is the scalar leaf.
		auto &c_orders_type = c_orders_ref.return_type;
		if (c_orders_type.id() != LogicalTypeId::LIST) {
			continue;
		}
		auto &order_struct = ListType::GetChildType(c_orders_type);
		if (order_struct.id() != LogicalTypeId::STRUCT ||
		    list_field.GetIndex() >= StructType::GetChildTypes(order_struct).size()) {
			continue;
		}
		auto &o_lineitems_type = StructType::GetChildTypes(order_struct)[list_field.GetIndex()].second;
		if (o_lineitems_type.id() != LogicalTypeId::LIST) {
			continue;
		}
		auto &lineitem_struct = ListType::GetChildType(o_lineitems_type);
		if (lineitem_struct.id() != LogicalTypeId::STRUCT ||
		    leaf_field >= StructType::GetChildTypes(lineitem_struct).size()) {
			continue;
		}
		auto leaf_type = StructType::GetChildTypes(lineitem_struct)[leaf_field].second;
		if (leaf_type.IsNested()) {
			continue; // prototype: scalar leaf only
		}
		auto new_list_type = LogicalType::LIST(leaf_type);

		// (1) scan produces LIST<leaf>; reader navigates the 2-step path [list_field, leaf_field]
		col_ids[c_orders_logical].SetType(new_list_type);
		get.nested_projection_map[phys] = {list_field.GetIndex(), leaf_field};
		// (2) collapse the two UNNESTs into UNNEST_B directly over GET: splice the GET up, drop mid_proj + inner
		outer.children[0] = std::move(inner.children[0]); // inner.children[0] is the GET
		// (3) UNNEST_B now unnests the flattened c_orders column of the GET
		bu_outer.child = make_uniq<BoundColumnRefExpression>(new_list_type,
		                                                     ColumnBinding(get.table_index, c_orders_logical));
		bu_outer.return_type = leaf_type;
		// (4) the outer unnest output is now the leaf scalar; drop struct_extract on it in phase 2
		flattened_outputs[ColumnBinding(outer.unnest_index, i)] = leaf_type;
		return true;
	}
	return false;
}

void FlattenUnnest::RewriteUnnests(LogicalOperator &op) {
	// children first: rewrite the deepest UNNEST/GET pairs before their parents
	for (auto &child : op.children) {
		RewriteUnnests(*child);
	}
	if (op.type != LogicalOperatorType::LOGICAL_UNNEST) {
		return;
	}
	auto &unnest = op.Cast<LogicalUnnest>();

	// Find the LogicalGet directly below this UNNEST (through projections only).
	LogicalOperator *cur = op.children.empty() ? nullptr : op.children[0].get();
	bool intervening_unnest = false;
	while (cur) {
		if (cur->type == LogicalOperatorType::LOGICAL_GET) {
			break;
		}
		if (cur->type == LogicalOperatorType::LOGICAL_UNNEST) {
			intervening_unnest = true;
			break;
		}
		if (cur->children.empty()) {
			return;
		}
		cur = cur->children[0].get();
	}
	if (intervening_unnest) {
		// two-level (or deeper) pattern
		TryFlattenTwoLevel(unnest);
		return;
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
		// single leaf sub-field only
		auto np = get.nested_projection_map.find(phys);
		if (np == get.nested_projection_map.end() || np->second.size() != 1) {
			continue;
		}
		idx_t leaf_idx = np->second[0];

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
		if (leaf_type.IsNested()) {
			continue;
		}
		auto new_list_type = LogicalType::LIST(leaf_type);

		col_ids[logical_idx].SetType(new_list_type);
		cref.return_type = new_list_type;
		bu.return_type = leaf_type;
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
	// phase 0: collect struct-field extraction uses per binding (needed to find the deep leaf field)
	CollectOperator(*op);
	// phase 1: detect + rewrite flatten patterns
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
