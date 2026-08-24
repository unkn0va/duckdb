//===----------------------------------------------------------------------===//
//                         DuckDB
//
// duckdb/planner/operator/logical_unnest.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/planner/logical_operator.hpp"

namespace duckdb {

//! LogicalUnnest represents the logical UNNEST operator.
class LogicalUnnest : public LogicalOperator {
public:
	static constexpr const LogicalOperatorType TYPE = LogicalOperatorType::LOGICAL_UNNEST;

public:
	explicit LogicalUnnest(idx_t unnest_index)
	    : LogicalOperator(LogicalOperatorType::LOGICAL_UNNEST), unnest_index(unnest_index) {
	}

	idx_t unnest_index;

	//! Element-level filters absorbed from a Filter that sat directly above this UNNEST.
	//! These are NOT predicates over this operator's output rows: each expression is
	//! evaluated against a single *element* of the unnested lists, where a
	//! BoundColumnRefExpression with binding (unnest_index, i) denotes one element of
	//! expressions[i]'s list. UNNEST drops the elements that do not satisfy them, so they
	//! never get expanded into output rows at all.
	//!
	//! Deliberately kept out of `expressions`: LogicalOperatorVisitor passes must not treat
	//! them as row-level expressions of this operator. The one pass that does need to see
	//! them is RemoveUnusedColumns, which visits them explicitly so the leaf fields they
	//! reference survive column pruning.
	//!
	//! Populated by FilterPushdown::PushdownUnnest, consumed by PhysicalUnnest.
	vector<unique_ptr<Expression>> element_filters;

public:
	vector<ColumnBinding> GetColumnBindings() override;
	InsertionOrderPreservingMap<string> ParamsToString() const override;
	void Serialize(Serializer &serializer) const override;
	static unique_ptr<LogicalOperator> Deserialize(Deserializer &deserializer);
	vector<idx_t> GetTableIndex() const override;
	string GetName() const override;

protected:
	void ResolveTypes() override;
};
} // namespace duckdb
