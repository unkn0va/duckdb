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
	LogicalPlanSQLExportResult ToSQL(LogicalPlanSQLExportContext &context,
	                                 const LogicalPlanVerificationPath &path) override;

	static constexpr const LogicalOperatorType TYPE = LogicalOperatorType::LOGICAL_UNNEST;

public:
	explicit LogicalUnnest(TableIndex unnest_index)
	    : LogicalOperator(LogicalOperatorType::LOGICAL_UNNEST), unnest_index(unnest_index) {
	}

	TableIndex unnest_index;

	//! Comprehension filters absorbed from a Filter below this UNNEST, revived from the
	//! `element_filters` field removed in fff6e6276e ("reset to projection pruning") but with
	//! different semantics: these are BoundComprehensionExpressions moved here by the roll-up
	//! rule (DataFusion's RollUpNestedFilter / Unnest.filters), not per-element row predicates.
	//!
	//! Deliberately kept out of `expressions`: LogicalOperatorVisitor passes must not treat them
	//! as row-level expressions of this operator.
	//!
	//! Nothing consumes them yet - a Filtered UNNEST operator would. Until then they are pure
	//! annotation: the predicate they describe is still evaluated by the Filter that stays above
	//! this UNNEST, so dropping them cannot change a result.
	vector<unique_ptr<Expression>> filters;

public:
	vector<ColumnBinding> GetColumnBindings() override;
	InsertionOrderPreservingMap<string> ParamsToString() const override;
	void Serialize(Serializer &serializer) const override;
	static unique_ptr<LogicalOperator> Deserialize(Deserializer &deserializer);
	vector<TableIndex> GetTableIndex() const override;
	string GetName() const override;

protected:
	void ResolveTypes() override;
};
} // namespace duckdb
