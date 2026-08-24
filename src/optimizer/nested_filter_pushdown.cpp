#include "duckdb/optimizer/nested_filter_pushdown.hpp"

#include "duckdb/common/enums/expression_type.hpp"
#include "duckdb/function/scalar/struct_utils.hpp"
#include "duckdb/planner/expression/bound_between_expression.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_comparison_expression.hpp"
#include "duckdb/planner/expression/bound_conjunction_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/expression/bound_function_expression.hpp"
#include "duckdb/planner/expression/bound_unnest_expression.hpp"
#include "duckdb/planner/filter/conjunction_filter.hpp"
#include "duckdb/planner/filter/constant_filter.hpp"
#include "duckdb/planner/filter/list_element_filter.hpp"
#include "duckdb/planner/filter/struct_filter.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/planner/operator/logical_projection.hpp"
#include "duckdb/planner/operator/logical_unnest.hpp"

namespace duckdb {

//! One level of nesting between a scan column and the value a predicate reads
struct NestedPathStep {
	//! true: step into the element of a LIST; false: step into struct field `child_idx`
	bool list_element;
	idx_t child_idx;
};

//===--------------------------------------------------------------------===//
// Translating the absorbed predicate into a filter on the element
//===--------------------------------------------------------------------===//

//! Collect the struct child indexes that lead from the UNNEST element to what `expr` reads.
//! Fails unless `expr` is a chain of struct_extracts rooted at the element itself - a cast or any
//! other wrapper in the chain means we cannot say which stored field the predicate reads.
static bool ExtractElementFieldPath(const Expression &expr, const idx_t unnest_index, vector<idx_t> &path) {
	if (expr.GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
		auto &colref = expr.Cast<BoundColumnRefExpression>();
		// column_index 0 is the only one: absorption only happens for a single-expression UNNEST
		return colref.binding.table_index == unnest_index && colref.binding.column_index == 0;
	}
	if (expr.GetExpressionClass() != ExpressionClass::BOUND_FUNCTION) {
		return false;
	}
	auto &function = expr.Cast<BoundFunctionExpression>();
	if (function.function.name != "struct_extract" && function.function.name != "struct_extract_at") {
		return false;
	}
	if (!function.bind_info || function.children.empty()) {
		return false;
	}
	if (function.children[0]->return_type.id() != LogicalTypeId::STRUCT) {
		return false;
	}
	if (!ExtractElementFieldPath(*function.children[0], unnest_index, path)) {
		return false;
	}
	path.push_back(function.bind_info->Cast<StructExtractBindData>().index);
	return true;
}

//! Wrap `leaf` in the StructFilters that walk `path` down from `type`
static unique_ptr<TableFilter> BuildStructPath(const LogicalType &type, const vector<idx_t> &path, idx_t depth,
                                              unique_ptr<TableFilter> leaf) {
	if (depth == path.size()) {
		return leaf;
	}
	if (type.id() != LogicalTypeId::STRUCT) {
		return nullptr;
	}
	auto &children = StructType::GetChildTypes(type);
	auto child_idx = path[depth];
	if (child_idx >= children.size()) {
		return nullptr;
	}
	auto child = BuildStructPath(children[child_idx].second, path, depth + 1, std::move(leaf));
	if (!child) {
		return nullptr;
	}
	return make_uniq<StructFilter>(child_idx, children[child_idx].first, std::move(child));
}

//! Build `field <comparison> constant` as a filter on the element, where `field_expr` reads a field
//! of the element and `constant` is the value it is compared against.
static unique_ptr<TableFilter> BuildComparison(const Expression &field_expr, const Value &constant,
                                              ExpressionType comparison, const idx_t unnest_index,
                                              const LogicalType &element_type) {
	vector<idx_t> path;
	if (!ExtractElementFieldPath(field_expr, unnest_index, path)) {
		return nullptr;
	}
	if (path.empty()) {
		// the predicate reads the element as a whole, not one of its fields - there is no leaf whose
		// statistics we could check
		return nullptr;
	}
	if (constant.IsNull()) {
		return nullptr;
	}
	if (constant.type() != field_expr.return_type) {
		// the comparison is on a different type than the stored field: leave it alone rather than
		// guess how the values relate
		return nullptr;
	}
	auto leaf = make_uniq<ConstantFilter>(comparison, constant);
	return BuildStructPath(element_type, path, 0, std::move(leaf));
}

static unique_ptr<TableFilter> TranslateElementPredicate(const Expression &expr, idx_t unnest_index,
                                                        const LogicalType &element_type);

//! AND: translating only some of the conjuncts is fine - pruning with fewer of them is conservative
static unique_ptr<TableFilter> TranslateConjunction(const BoundConjunctionExpression &conjunction,
                                                    const idx_t unnest_index, const LogicalType &element_type) {
	const auto is_and = conjunction.GetExpressionType() == ExpressionType::CONJUNCTION_AND;
	vector<unique_ptr<TableFilter>> children;
	for (auto &child : conjunction.children) {
		auto child_filter = TranslateElementPredicate(*child, unnest_index, element_type);
		if (!child_filter) {
			if (is_and) {
				continue;
			}
			// OR: a branch we cannot translate can be satisfied by anything, so the whole
			// disjunction tells us nothing
			return nullptr;
		}
		children.push_back(std::move(child_filter));
	}
	if (children.empty()) {
		return nullptr;
	}
	if (children.size() == 1) {
		return std::move(children[0]);
	}
	if (is_and) {
		auto result = make_uniq<ConjunctionAndFilter>();
		result->child_filters = std::move(children);
		return std::move(result);
	}
	auto result = make_uniq<ConjunctionOrFilter>();
	result->child_filters = std::move(children);
	return std::move(result);
}

static unique_ptr<TableFilter> TranslateElementPredicate(const Expression &expr, const idx_t unnest_index,
                                                        const LogicalType &element_type) {
	switch (expr.GetExpressionClass()) {
	case ExpressionClass::BOUND_COMPARISON: {
		auto &comparison = expr.Cast<BoundComparisonExpression>();
		auto type = comparison.GetExpressionType();
		if (type != ExpressionType::COMPARE_EQUAL && type != ExpressionType::COMPARE_NOTEQUAL &&
		    type != ExpressionType::COMPARE_LESSTHAN && type != ExpressionType::COMPARE_LESSTHANOREQUALTO &&
		    type != ExpressionType::COMPARE_GREATERTHAN && type != ExpressionType::COMPARE_GREATERTHANOREQUALTO) {
			return nullptr;
		}
		if (comparison.right->GetExpressionClass() == ExpressionClass::BOUND_CONSTANT) {
			auto &constant = comparison.right->Cast<BoundConstantExpression>();
			return BuildComparison(*comparison.left, constant.value, type, unnest_index, element_type);
		}
		if (comparison.left->GetExpressionClass() == ExpressionClass::BOUND_CONSTANT) {
			auto &constant = comparison.left->Cast<BoundConstantExpression>();
			return BuildComparison(*comparison.right, constant.value, FlipComparisonExpression(type), unnest_index,
			                       element_type);
		}
		// field-vs-field comparisons (l_commitdate < l_receiptdate) say nothing about either field's
		// range on its own
		return nullptr;
	}
	case ExpressionClass::BOUND_BETWEEN: {
		auto &between = expr.Cast<BoundBetweenExpression>();
		if (between.lower->GetExpressionClass() != ExpressionClass::BOUND_CONSTANT ||
		    between.upper->GetExpressionClass() != ExpressionClass::BOUND_CONSTANT) {
			return nullptr;
		}
		auto lower = BuildComparison(*between.input, between.lower->Cast<BoundConstantExpression>().value,
		                             between.LowerComparisonType(), unnest_index, element_type);
		auto upper = BuildComparison(*between.input, between.upper->Cast<BoundConstantExpression>().value,
		                             between.UpperComparisonType(), unnest_index, element_type);
		if (!lower) {
			return upper;
		}
		if (!upper) {
			return lower;
		}
		auto result = make_uniq<ConjunctionAndFilter>();
		result->child_filters.push_back(std::move(lower));
		result->child_filters.push_back(std::move(upper));
		return std::move(result);
	}
	case ExpressionClass::BOUND_CONJUNCTION:
		return TranslateConjunction(expr.Cast<BoundConjunctionExpression>(), unnest_index, element_type);
	default:
		return nullptr;
	}
}

//===--------------------------------------------------------------------===//
// Tracing the unnested list back to its scan
//===--------------------------------------------------------------------===//

//! Find the operator below (and including) `op` that defines `binding`. Only operator types whose
//! rows map one-to-one onto their child's rows are traversed - see the class comment.
static optional_ptr<LogicalOperator> FindDefiningOperator(LogicalOperator &op, const ColumnBinding &binding) {
	switch (op.type) {
	case LogicalOperatorType::LOGICAL_GET:
		if (op.Cast<LogicalGet>().table_index == binding.table_index) {
			return op;
		}
		return nullptr;
	case LogicalOperatorType::LOGICAL_PROJECTION:
		if (op.Cast<LogicalProjection>().table_index == binding.table_index) {
			return op;
		}
		// a projection rebinds its whole output, so nothing below it can be referenced from above
		return nullptr;
	case LogicalOperatorType::LOGICAL_UNNEST:
		if (op.Cast<LogicalUnnest>().unnest_index == binding.table_index) {
			return op;
		}
		break;
	case LogicalOperatorType::LOGICAL_FILTER:
	case LogicalOperatorType::LOGICAL_ORDER_BY:
		break;
	default:
		return nullptr;
	}
	for (auto &child : op.children) {
		auto result = FindDefiningOperator(*child, binding);
		if (result) {
			return result;
		}
	}
	return nullptr;
}

//! Trace `expr` - which evaluates to the LIST some UNNEST expands - down to the scan column holding
//! it, collecting the nesting steps that lead from that column to `expr`'s value.
static bool ResolveNestedPath(LogicalOperator &op, const Expression &expr, optional_ptr<LogicalGet> &get,
                              idx_t &column_binding_index, vector<NestedPathStep> &steps) {
	switch (expr.GetExpressionClass()) {
	case ExpressionClass::BOUND_FUNCTION: {
		auto &function = expr.Cast<BoundFunctionExpression>();
		if (function.function.name != "struct_extract" && function.function.name != "struct_extract_at") {
			return false;
		}
		if (!function.bind_info || function.children.empty()) {
			return false;
		}
		if (function.children[0]->return_type.id() != LogicalTypeId::STRUCT) {
			return false;
		}
		if (!ResolveNestedPath(op, *function.children[0], get, column_binding_index, steps)) {
			return false;
		}
		steps.push_back({false, function.bind_info->Cast<StructExtractBindData>().index});
		return true;
	}
	case ExpressionClass::BOUND_COLUMN_REF: {
		auto &colref = expr.Cast<BoundColumnRefExpression>();
		auto defining_op = FindDefiningOperator(op, colref.binding);
		if (!defining_op) {
			return false;
		}
		switch (defining_op->type) {
		case LogicalOperatorType::LOGICAL_GET: {
			auto &child_get = defining_op->Cast<LogicalGet>();
			if (colref.binding.column_index >= child_get.GetColumnIds().size()) {
				return false;
			}
			get = child_get;
			column_binding_index = colref.binding.column_index;
			return true;
		}
		case LogicalOperatorType::LOGICAL_PROJECTION: {
			auto &projection = defining_op->Cast<LogicalProjection>();
			if (colref.binding.column_index >= projection.expressions.size()) {
				return false;
			}
			return ResolveNestedPath(*projection.children[0], *projection.expressions[colref.binding.column_index],
			                         get, column_binding_index, steps);
		}
		case LogicalOperatorType::LOGICAL_UNNEST: {
			// the reference is to one element of a list that this UNNEST expands
			auto &child_unnest = defining_op->Cast<LogicalUnnest>();
			if (colref.binding.column_index >= child_unnest.expressions.size()) {
				return false;
			}
			auto &unnest_expr = *child_unnest.expressions[colref.binding.column_index];
			if (unnest_expr.GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
				return false;
			}
			auto &bound_unnest = unnest_expr.Cast<BoundUnnestExpression>();
			if (!ResolveNestedPath(*child_unnest.children[0], *bound_unnest.child, get, column_binding_index, steps)) {
				return false;
			}
			steps.push_back({true, 0});
			return true;
		}
		default:
			return false;
		}
	}
	default:
		return false;
	}
}

//! Wrap `leaf` in the filters that walk `steps` down from `type`
static unique_ptr<TableFilter> BuildNestedPath(const LogicalType &type, const vector<NestedPathStep> &steps,
                                              idx_t depth, unique_ptr<TableFilter> leaf) {
	if (depth == steps.size()) {
		return leaf;
	}
	auto &step = steps[depth];
	if (step.list_element) {
		if (type.id() != LogicalTypeId::LIST) {
			return nullptr;
		}
		auto child = BuildNestedPath(ListType::GetChildType(type), steps, depth + 1, std::move(leaf));
		if (!child) {
			return nullptr;
		}
		return make_uniq<ListElementFilter>(std::move(child));
	}
	if (type.id() != LogicalTypeId::STRUCT) {
		return nullptr;
	}
	auto &children = StructType::GetChildTypes(type);
	if (step.child_idx >= children.size()) {
		return nullptr;
	}
	auto child = BuildNestedPath(children[step.child_idx].second, steps, depth + 1, std::move(leaf));
	if (!child) {
		return nullptr;
	}
	return make_uniq<StructFilter>(step.child_idx, children[step.child_idx].first, std::move(child));
}

//===--------------------------------------------------------------------===//
// Driver
//===--------------------------------------------------------------------===//

static void PushdownUnnestElementFilters(LogicalUnnest &unnest) {
	if (unnest.element_filters.empty() || unnest.expressions.size() != 1) {
		return;
	}
	auto &unnest_expr = *unnest.expressions[0];
	if (unnest_expr.GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
		return;
	}
	auto &list_expr = *unnest_expr.Cast<BoundUnnestExpression>().child;
	if (list_expr.return_type.id() != LogicalTypeId::LIST) {
		return;
	}
	auto &element_type = ListType::GetChildType(list_expr.return_type);

	// which scan column holds the list, and how do we get from that column to the list?
	optional_ptr<LogicalGet> get;
	idx_t column_binding_index = 0;
	vector<NestedPathStep> steps;
	if (!ResolveNestedPath(*unnest.children[0], list_expr, get, column_binding_index, steps)) {
		return;
	}
	if (!get->function.filter_pushdown) {
		return;
	}
	auto &column_ids = get->GetColumnIds();
	auto &column_index = column_ids[column_binding_index];
	if (column_index.IsPushdownExtract()) {
		// the scan hands us the extracted field rather than the column, so the path we resolved does
		// not describe what it reads
		return;
	}
	auto column_type = get->GetColumnType(column_index);

	// the predicate applies to an element of the list we just resolved
	auto element_steps = steps;
	element_steps.push_back({true, 0});

	for (auto &element_filter : unnest.element_filters) {
		auto filter = TranslateElementPredicate(*element_filter, unnest.unnest_index, element_type);
		if (!filter) {
			continue;
		}
		auto nested_filter = BuildNestedPath(column_type, element_steps, 0, std::move(filter));
		if (!nested_filter) {
			continue;
		}
		get->table_filters.PushFilter(column_index, std::move(nested_filter));
	}
}

void NestedFilterPushdown::Optimize(LogicalOperator &op) {
	for (auto &child : op.children) {
		Optimize(*child);
	}
	if (op.type == LogicalOperatorType::LOGICAL_UNNEST) {
		PushdownUnnestElementFilters(op.Cast<LogicalUnnest>());
	}
}

} // namespace duckdb
