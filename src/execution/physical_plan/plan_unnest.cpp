#include "duckdb/execution/operator/projection/physical_unnest.hpp"
#include "duckdb/execution/physical_plan_generator.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_reference_expression.hpp"
#include "duckdb/planner/expression_iterator.hpp"
#include "duckdb/planner/operator/logical_unnest.hpp"

namespace duckdb {

//! Lower an absorbed element filter from binding form to reference form.
//! In LogicalUnnest::element_filters a BoundColumnRefExpression bound to (unnest_index, i)
//! denotes one element of expressions[i]'s list. At runtime the predicate is evaluated
//! against a chunk holding exactly one such element column per UNNEST, so those references
//! become BoundReferenceExpressions with the same index.
//! Note that ColumnBindingResolver never sees element_filters (they are not part of
//! LogicalOperator::expressions), which is why we resolve them here instead.
static void LowerElementFilter(unique_ptr<Expression> &expr, const idx_t unnest_index) {
	if (expr->GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
		auto &colref = expr->Cast<BoundColumnRefExpression>();
		D_ASSERT(colref.binding.table_index == unnest_index);
		expr = make_uniq<BoundReferenceExpression>(colref.GetAlias(), colref.return_type,
		                                           colref.binding.column_index);
		return;
	}
	ExpressionIterator::EnumerateChildren(
	    *expr, [&](unique_ptr<Expression> &child) { LowerElementFilter(child, unnest_index); });
}

PhysicalOperator &PhysicalPlanGenerator::CreatePlan(LogicalUnnest &op) {
	D_ASSERT(op.children.size() == 1);
	auto &plan = CreatePlan(*op.children[0]);
	for (auto &filter : op.element_filters) {
		LowerElementFilter(filter, op.unnest_index);
	}
	auto &unnest = Make<PhysicalUnnest>(op.types, std::move(op.expressions), std::move(op.element_filters),
	                                    op.estimated_cardinality);
	unnest.children.push_back(plan);
	return unnest;
}

} // namespace duckdb
