//===----------------------------------------------------------------------===//
//                         DuckDB
//
// duckdb/optimizer/prenest_filter_pushdown.hpp
//
// PROBE CODE. Finds conjuncts of a LogicalFilter that reduce, through UNNEST and
// PROJECTION, to "<element struct field> <cmp> <constant>" over one LIST column
// of a scan, and hands them to that scan as a PrenestFilterSpec so the reader can
// drop elements before the list is assembled.
//
// The extracted conjuncts are deliberately LEFT IN PLACE in the LogicalFilter:
// the predicate is evaluated twice, which makes a mis-pushed predicate a
// performance bug rather than a correctness bug.
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/planner/logical_operator.hpp"

namespace duckdb {
class ClientContext;

class PrenestFilterPushdown {
public:
	explicit PrenestFilterPushdown(ClientContext &context) : context(context) {
	}

	//! Extract pre-nest predicates and attach them to the scans they belong to.
	//! Does nothing unless `parquet_prenest_auto` is set.
	void Optimize(LogicalOperator &plan);

private:
	ClientContext &context;
};

} // namespace duckdb
