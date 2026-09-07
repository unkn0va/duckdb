//===----------------------------------------------------------------------===//
//                         DuckDB
//
// prenest_filter.hpp
//
// PROBE CODE. Element-level predicate applied during list assembly in
// ListColumnReader. Supplied manually via the `parquet_prenest_filter`
// setting; nothing in the optimizer, planner or binder is involved.
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/common/atomic.hpp"
#include "duckdb/common/types/selection_vector.hpp"
#include "duckdb/common/types/vector.hpp"
#include "duckdb/planner/table_filter.hpp"
#include "duckdb/planner/table_filter_state.hpp"

namespace duckdb {
class ClientContext;

//! Instrumentation. Read with parquet_prenest_stat('<name>'); 'reset' zeroes.
struct PrenestStats {
	atomic<idx_t> elements_decoded {0};
	atomic<idx_t> elements_appended {0};
	atomic<idx_t> inner_iterations {0};
	atomic<idx_t> carryovers {0};
	atomic<idx_t> carryover_flattens {0};
	atomic<idx_t> predicate_elements {0};

	void Reset() {
		elements_decoded = 0;
		elements_appended = 0;
		inner_iterations = 0;
		carryovers = 0;
		carryover_flattens = 0;
		predicate_elements = 0;
	}
	static PrenestStats &Get();
};

struct PrenestCondition {
	idx_t child_idx;
	unique_ptr<TableFilter> filter;
	unique_ptr<TableFilterState> state;
};

//! A conjunction of <struct field> <cmp> <constant> conditions over the element
//! struct of one LIST column.
class PrenestFilter {
public:
	//! Parse "list_name: f op v AND f op v ...". Returns nullptr for an empty spec.
	static unique_ptr<PrenestFilter> Parse(const string &spec);

	//! Resolve field names against a concrete element STRUCT type. Returns false
	//! if any referenced field is absent - the caller then keeps the stock path.
	bool Bind(ClientContext &context, const LogicalType &element_type);

	//! Names referenced by the conjunction, for the "is this the right list" test.
	const vector<string> &FieldNames() const {
		return field_names;
	}
	const vector<idx_t> &FieldChildIndexes() const {
		return field_child_indexes;
	}

	//! Narrow `sel` to the surviving elements of `element_vector` and set keep[].
	//! `element_vector` must be flat. Returns the number of survivors.
	idx_t Apply(Vector &element_vector, idx_t count, SelectionVector &sel, bool *keep) const;

private:
	struct RawCondition {
		string field;
		ExpressionType comparison;
		string literal;
	};
	string list_name;
	vector<RawCondition> raw_conditions;
	vector<string> field_names;
	vector<idx_t> field_child_indexes;
	vector<PrenestCondition> conditions;
};

} // namespace duckdb
