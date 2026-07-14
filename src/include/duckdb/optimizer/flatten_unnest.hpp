//===----------------------------------------------------------------------===//
//                         DuckDB
//
// duckdb/optimizer/flatten_unnest.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/planner/logical_operator.hpp"
#include "duckdb/planner/logical_operator_visitor.hpp"
#include "duckdb/planner/column_binding_map.hpp"

namespace duckdb {

//! [Rey hybrid / approach C] FlattenUnnest rewrites the single-node "scan a nested column, immediately UNNEST it,
//! and use only leaf sub-fields" pattern so that:
//!   - the scan (LogicalGet) is told to emit LIST<leaf> for that column (ColumnIndex::SetType), matching the
//!     collapse reader that skips STRUCT assembly, and
//!   - the UNNEST unnests that LIST<leaf> directly, and
//!   - the parent projection's struct_extract on the unnest output is dropped (the output is now the leaf scalar).
//! This runs after column pruning (which populates LogicalGet::flatten_columns / nested_projection_map).
//! Prototype scope: single nesting level, single leaf sub-field per flatten column.
class FlattenUnnest : public LogicalOperatorVisitor {
public:
	unique_ptr<LogicalOperator> Optimize(unique_ptr<LogicalOperator> op);

protected:
	//! Phase 2: rewrite struct_extract(<flattened unnest output>, field) into a plain column reference.
	unique_ptr<Expression> VisitReplace(BoundFunctionExpression &expr, unique_ptr<Expression> *expr_ptr) override;

private:
	//! Phase 1: find qualifying UNNEST-over-GET patterns and retype GET column + UNNEST expr.
	void RewriteUnnests(LogicalOperator &op);

	//! Unnest output binding -> new leaf type; struct_extract on these bindings is rewritten in phase 2.
	column_binding_map_t<LogicalType> flattened_outputs;
};

} // namespace duckdb
