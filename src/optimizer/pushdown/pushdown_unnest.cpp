#include "duckdb/optimizer/filter_pushdown.hpp"
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/catalog/catalog.hpp"
#include "duckdb/catalog/catalog_entry/scalar_function_catalog_entry.hpp"
#include "duckdb/common/enums/on_entry_not_found.hpp"
#include "duckdb/function/function_binder.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_comparison_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/expression/bound_function_expression.hpp"
#include "duckdb/planner/expression/bound_lambda_expression.hpp"
#include "duckdb/planner/expression/bound_reference_expression.hpp"
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

// Recursively replace every reference to the unnest output column (unnest_index, target_col) in `expr`
// with a reference to the lambda parameter, i.e. BoundReferenceExpression at chunk index 0 (the list
// child element; valid only for a single-parameter, zero-capture lambda). Returns false if `expr`
// references an unnest output column OTHER than target_col (predicate combines multiple unnested lists,
// which a single list_filter cannot express).
static bool ReplaceUnnestRefWithLambdaParam(unique_ptr<Expression> &expr, idx_t unnest_index, idx_t target_col,
                                            const LogicalType &elem_type) {
	if (expr->GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
		auto &col = expr->Cast<BoundColumnRefExpression>();
		if (col.binding.table_index == unnest_index) {
			if (col.binding.column_index != target_col) {
				return false;
			}
			expr = make_uniq<BoundReferenceExpression>(elem_type, 0);
		}
		return true;
	}
	bool ok = true;
	ExpressionIterator::EnumerateChildren(*expr, [&](unique_ptr<Expression> &child) {
		if (!ReplaceUnnestRefWithLambdaParam(child, unnest_index, target_col, elem_type)) {
			ok = false;
		}
	});
	return ok;
}

// Recursively scan `expr` for references to unnest output columns (table_index == unnest_index).
// Records the first such column index in target_col; sets `multiple` if a different one is also found.
// Sets `foreign` if a column reference OUTSIDE this unnest is found: such a predicate correlates the
// unnest element with an external (pass-through) column, which the zero-capture lambda synthesis below
// cannot express (it would require a lambda capture), so the caller must bail.
static void FindUnnestColumn(Expression &expr, idx_t unnest_index, bool &found, bool &multiple, bool &foreign,
                             idx_t &target_col) {
	if (expr.GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
		auto &col = expr.Cast<BoundColumnRefExpression>();
		if (col.binding.table_index == unnest_index) {
			if (!found) {
				target_col = col.binding.column_index;
				found = true;
			} else if (col.binding.column_index != target_col) {
				multiple = true;
			}
		} else {
			foreign = true;
		}
		return;
	}
	ExpressionIterator::EnumerateChildren(expr, [&](Expression &child) {
		FindUnnestColumn(child, unnest_index, found, multiple, foreign, target_col);
	});
}

// Sub-step 2 (general fallback): for an unnest-output filter that cannot be pushed down directly and is
// not handled by the scalar-monotonic fast path, synthesize the weakened list-level necessary condition
//   len(list_filter(list, x -> <predicate with the unnest ref replaced by x>)) > 0
// and push it into the child. Works for any predicate shape (incl. struct-field access, =, etc.) as long
// as it references exactly ONE unnest output column. Returns nullptr (caller no-ops) otherwise, or if the
// required core_functions are not loaded.
static unique_ptr<Expression> TryBuildListFilterExists(ClientContext &context, LogicalUnnest &unnest,
                                                       Expression &filter) {
	// A volatile predicate (e.g. random(), nextval()) must not be pushed down: the synthesized child
	// filter would evaluate the volatile subexpression with draws independent of the retained filter
	// above UNNEST, so a row that satisfies the original predicate could be dropped by the child before
	// the exact filter ever sees it. Bail (correctness-safe no-op). Note IsVolatile() excludes
	// consistent-within-query functions (now() etc.), which are safe to evaluate on both sides.
	if (filter.IsVolatile()) {
		return nullptr;
	}

	// find the single unnest output column referenced by the predicate
	bool found = false;
	bool multiple = false;
	bool foreign = false;
	idx_t target_col = 0;
	FindUnnestColumn(filter, unnest.unnest_index, found, multiple, foreign, target_col);
	if (!found || multiple || foreign) {
		return nullptr;
	}
	if (target_col >= unnest.expressions.size() ||
	    unnest.expressions[target_col]->GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
		return nullptr;
	}
	auto &bound_unnest = unnest.expressions[target_col]->Cast<BoundUnnestExpression>();
	auto elem_type = bound_unnest.return_type;

	// build the lambda body: a copy of the predicate with the unnest ref replaced by the lambda parameter
	auto lambda_body = filter.Copy();
	if (!ReplaceUnnestRefWithLambdaParam(lambda_body, unnest.unnest_index, target_col, elem_type)) {
		return nullptr;
	}

	// catalog lookup + bind, wrapped so any failure degrades to a no-op (see TryBuildListExistsFilter).
	try {
		auto &catalog = Catalog::GetSystemCatalog(context);
		auto list_filter_entry = catalog.GetEntry<ScalarFunctionCatalogEntry>(context, DEFAULT_SCHEMA, "list_filter",
		                                                                      OnEntryNotFound::RETURN_NULL);
		auto len_entry =
		    catalog.GetEntry<ScalarFunctionCatalogEntry>(context, DEFAULT_SCHEMA, "len", OnEntryNotFound::RETURN_NULL);
		if (!list_filter_entry || !len_entry) {
			return nullptr;
		}

		// list_filter(list, lambda) ; the parameter is BoundReferenceExpression(elem_type, 0), no captures
		auto bound_lambda = make_uniq<BoundLambdaExpression>(ExpressionType::LAMBDA, LogicalType::LAMBDA,
		                                                     std::move(lambda_body), 1);
		vector<unique_ptr<Expression>> filter_args;
		filter_args.push_back(bound_unnest.child->Copy());
		filter_args.push_back(std::move(bound_lambda));
		auto list_filter_fun = list_filter_entry->functions.GetFunctionByArguments(
		    context, {filter_args[0]->return_type, LogicalType::LAMBDA});
		FunctionBinder binder(context);
		auto bound_list_filter = binder.BindScalarFunction(list_filter_fun, std::move(filter_args));

		// FunctionBinder::BindScalarFunction runs ListFilterBind (which moves the lambda body into the
		// function's bind data) but, unlike the ExpressionBinder lambda path, leaves the BoundLambdaExpression
		// in the children. ExpressionIterator cannot traverse BOUND_LAMBDA, so we must remove it and splice in
		// its captures (none here) exactly as BindLambdaFunction does.
		if (bound_list_filter->GetExpressionClass() != ExpressionClass::BOUND_FUNCTION) {
			return nullptr;
		}
		auto &filter_func = bound_list_filter->Cast<BoundFunctionExpression>();
		if (filter_func.children.size() > 1 &&
		    filter_func.children[1]->GetExpressionClass() == ExpressionClass::BOUND_LAMBDA) {
			auto lambda_child = std::move(filter_func.children[1]);
			filter_func.children.erase_at(1);
			for (auto &capture : lambda_child->Cast<BoundLambdaExpression>().captures) {
				filter_func.children.push_back(std::move(capture));
			}
		}

		// len(list_filter(...))
		vector<unique_ptr<Expression>> len_args;
		len_args.push_back(std::move(bound_list_filter));
		auto len_fun = len_entry->functions.GetFunctionByArguments(context, {len_args[0]->return_type});
		auto bound_len = binder.BindScalarFunction(len_fun, std::move(len_args));

		// len(...) > 0
		return make_uniq<BoundComparisonExpression>(ExpressionType::COMPARE_GREATERTHAN, std::move(bound_len),
		                                            make_uniq<BoundConstantExpression>(Value::BIGINT(0)));
	} catch (const std::exception &) {
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
			if (!derived) {
				// scalar-monotonic fast path did not apply; fall back to the general
				// list_filter form (handles struct-field access, non-monotonic predicates, etc.)
				derived = TryBuildListFilterExists(GetContext(), unnest, *f.filter);
			}
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
