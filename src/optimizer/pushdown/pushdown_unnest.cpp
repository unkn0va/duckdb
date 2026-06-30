#include "duckdb/optimizer/filter_pushdown.hpp"
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/catalog/catalog.hpp"
#include "duckdb/catalog/catalog_entry/scalar_function_catalog_entry.hpp"
#include "duckdb/common/enums/on_entry_not_found.hpp"
#include "duckdb/function/function_binder.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_comparison_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/expression/bound_unnest_expression.hpp"
#include "duckdb/planner/expression_iterator.hpp"
#include "duckdb/planner/operator/logical_empty_result.hpp"
#include "duckdb/planner/operator/logical_unnest.hpp"

namespace duckdb {

// Sub-step 1 (beachhead): for an unnest-output filter that cannot be pushed down directly,
// try to synthesize a weakened "list-level exists" necessary condition that CAN be pushed into
// the child. Scope is intentionally narrow and lambda-free: a bare monotonic comparison
// (col >/>=/</<= const) on a SCALAR unnest column, rewritten as list_max/list_min(list) OP const.
// Returns nullptr (caller no-ops) for anything outside this scope, or if core_functions is not loaded.
static unique_ptr<Expression> TryBuildListExistsFilter(ClientContext &context, LogicalUnnest &unnest,
                                                       Expression &filter) {
	if (filter.GetExpressionClass() != ExpressionClass::BOUND_COMPARISON) {
		return nullptr;
	}
	auto &cmp = filter.Cast<BoundComparisonExpression>();
	auto &left = *cmp.left;
	auto &right = *cmp.right;

	// identify which side references the unnest output; orient so the column is conceptually "left"
	BoundColumnRefExpression *col_ref = nullptr;
	Expression *const_side = nullptr;
	auto cmp_type = cmp.type;
	if (left.GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF && right.IsFoldable()) {
		col_ref = &left.Cast<BoundColumnRefExpression>();
		const_side = &right;
	} else if (right.GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF && left.IsFoldable()) {
		col_ref = &right.Cast<BoundColumnRefExpression>();
		const_side = &left;
		cmp_type = FlipComparisonExpression(cmp_type); // normalize so the column is on the left
	} else {
		return nullptr;
	}

	// the column must reference an unnest-produced output column
	if (col_ref->binding.table_index != unnest.unnest_index) {
		return nullptr;
	}
	auto out_idx = col_ref->binding.column_index;
	if (out_idx >= unnest.expressions.size()) {
		return nullptr;
	}
	auto &unnest_expr = unnest.expressions[out_idx];
	if (unnest_expr->GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
		return nullptr;
	}
	auto &bound_unnest = unnest_expr->Cast<BoundUnnestExpression>();

	// sub-step 1 scope: scalar element only (lambda-free). struct/list/map elements are deferred to sub-step 2.
	if (bound_unnest.return_type.IsNested()) {
		return nullptr;
	}

	// monotonic comparison: max for >, >= ; min for <, <=
	string agg_name;
	switch (cmp_type) {
	case ExpressionType::COMPARE_GREATERTHAN:
	case ExpressionType::COMPARE_GREATERTHANOREQUALTO:
		agg_name = "max";
		break;
	case ExpressionType::COMPARE_LESSTHAN:
	case ExpressionType::COMPARE_LESSTHANOREQUALTO:
		agg_name = "min";
		break;
	default:
		return nullptr;
	}

	// Catalog lookup + bind, wrapped so that ANY failure degrades to a no-op rather than failing the
	// query: core_functions not loaded (RETURN_NULL), no matching function, or an unexpected throw
	// (e.g. GetEntry throws on a catalog-entry-type mismatch even with RETURN_NULL). This rewrite is
	// purely a performance optimization, so abandoning it is always correctness-safe.
	// NOTE: list_max/list_min are macros; the underlying scalar function is list_aggregate(list, name).
	try {
		auto &catalog = Catalog::GetSystemCatalog(context);
		auto fun_entry = catalog.GetEntry<ScalarFunctionCatalogEntry>(context, DEFAULT_SCHEMA, "list_aggregate",
		                                                              OnEntryNotFound::RETURN_NULL);
		if (!fun_entry) {
			return nullptr;
		}

		// build list_aggregate(list, 'max'|'min')
		vector<unique_ptr<Expression>> agg_args;
		agg_args.push_back(bound_unnest.child->Copy());
		agg_args.push_back(make_uniq<BoundConstantExpression>(Value(agg_name)));
		auto agg_fun =
		    fun_entry->functions.GetFunctionByArguments(context, {agg_args[0]->return_type, agg_args[1]->return_type});
		FunctionBinder binder(context);
		auto bound_agg = binder.BindScalarFunction(agg_fun, std::move(agg_args));

		// build  list_aggregate(list, 'max'|'min') OP const
		return make_uniq<BoundComparisonExpression>(cmp_type, std::move(bound_agg), const_side->Copy());
	} catch (const std::exception &) {
		// any failure -> abandon the optimization (correctness-safe no-op)
		return nullptr;
	}
}

unique_ptr<LogicalOperator> FilterPushdown::PushdownUnnest(unique_ptr<LogicalOperator> op) {
	D_ASSERT(op->type == LogicalOperatorType::LOGICAL_UNNEST);
	auto &unnest = op->Cast<LogicalUnnest>();
	// push filter through logical projection
	// all the BoundColumnRefExpressions in the filter should refer to the LogicalProjection
	// we can rewrite them by replacing those references with the expression of the LogicalProjection node
	FilterPushdown child_pushdown(optimizer, convert_mark_joins);
	// There are some expressions can not be pushed down. We should keep them
	// and add an extra filter operator.
	vector<unique_ptr<Expression>> remain_expressions;
	for (auto &filter : filters) {
		auto &f = *filter;
		auto can_push = true;
		for (auto &binding : f.bindings) {
			if (binding == unnest.unnest_index) {
				can_push = false;
				break;
			}
		}
		// if the expression index table index is the unnest index, then the filter is on the
		// unnest, and it should not be pushed down.
		if (!can_push) {
			// (B) filter on an unnest-produced value: the original filter cannot be pushed down,
			// but we may be able to push a weakened list-level necessary condition into the child
			// (sub-step 1: scalar list + monotonic comparison -> list_max/list_min). The original
			// filter is still kept above UNNEST to do the exact per-element filtering.
			auto derived = TryBuildListExistsFilter(GetContext(), unnest, *f.filter);
			if (derived) {
				if (child_pushdown.AddFilter(std::move(derived)) == FilterResult::UNSATISFIABLE) {
					// derived filter statically evaluates to false, strip tree
					return make_uniq<LogicalEmptyResult>(std::move(op));
				}
			}
			remain_expressions.push_back(std::move(f.filter));
		} else {
			// add the filter to the child pushdown
			if (child_pushdown.AddFilter(std::move(f.filter)) == FilterResult::UNSATISFIABLE) {
				// filter statically evaluates to false, strip tree
				return make_uniq<LogicalEmptyResult>(std::move(op));
			}
		}
	}
	child_pushdown.GenerateFilters();
	// now push into children
	op->children[0] = child_pushdown.Rewrite(std::move(op->children[0]));
	if (op->children[0]->type == LogicalOperatorType::LOGICAL_EMPTY_RESULT) {
		// child returns an empty result: generate an empty result here too
		return make_uniq<LogicalEmptyResult>(std::move(op));
	}
	return AddLogicalFilter(std::move(op), std::move(remain_expressions));
}

} // namespace duckdb
