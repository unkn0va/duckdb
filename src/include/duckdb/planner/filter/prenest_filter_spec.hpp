//===----------------------------------------------------------------------===//
//                         DuckDB
//
// duckdb/planner/filter/prenest_filter_spec.hpp
//
// PROBE CODE. The format-agnostic description of an element-level pre-nest
// predicate: a conjunction over the element struct of one LIST column. The
// optimizer produces it, a file reader that supports pre-nest filtering
// consumes it (currently only Parquet).
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/common/enums/expression_type.hpp"
#include "duckdb/common/string.hpp"
#include "duckdb/common/vector.hpp"

namespace duckdb {

//! One "<field> <cmp> <literal>" term. The literal stays a string here - the
//! reader casts it to the field's real type once it knows the element type.
struct PrenestRawCondition {
	string field;
	ExpressionType comparison;
	string literal;
};

//! A pre-nest predicate carried from the bind/optimize phase down to the readers.
//! Empty means "nothing was injected" and the reader keeps its normal behaviour.
struct PrenestFilterSpec {
	string list_name;
	vector<PrenestRawCondition> conditions;

	bool empty() const {
		return conditions.empty();
	}
};

} // namespace duckdb
