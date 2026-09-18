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
#include "duckdb/common/shared_ptr.hpp"
#include "duckdb/common/string.hpp"
#include "duckdb/common/vector.hpp"
#include "duckdb/planner/expression.hpp"

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
	//! Root-relative path of the target LIST, in the optimizer's RenderPath spelling:
	//! field names joined by '.', with "[]" appended for each list-element step, e.g.
	//! "c_orders[].o_lineitems". This is what identifies the list to the reader - a bare
	//! name cannot, because one name may occur at several depths in a file.
	//!
	//! Empty when the predicate came from the `parquet_prenest_filter` setting, which
	//! speaks names rather than paths; the reader resolves it against the file schema.
	string list_path;
	//! Last segment of `list_path`. Not an identifier - two different lists can share it.
	//! Kept because it is what the counters are keyed on and what the setting accepts.
	string list_name;
	vector<PrenestRawCondition> conditions;
	//! The predicate the reader actually evaluates, over the element STRUCT: its leaves are
	//! BoundReferenceExpressions indexed by position in that struct, which is how
	//! PrenestFilterPushdown::Flatten leaves them. Shared rather than owned because
	//! ParquetOptions is copied by value to every reader of the scan; the expression is
	//! read-only during execution and each reader builds its own ExpressionExecutor over it,
	//! which is how DuckDB's physical operators share expressions between threads.
	//!
	//! Null when the predicate came from the `parquet_prenest_filter` setting, which is a
	//! string; the reader compiles that into the same shape in PrenestFilter::Bind.
	shared_ptr<Expression> predicate;

	bool empty() const {
		return conditions.empty();
	}
};

} // namespace duckdb
