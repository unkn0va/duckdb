//===----------------------------------------------------------------------===//
//                         DuckDB
//
// prenest_filter.hpp
//
// PROBE CODE. Element-level predicate applied during list assembly in
// ListColumnReader. Supplied either by PrenestFilterPushdown (one spec per LIST
// column of a scan) or manually via the `parquet_prenest_filter` setting.
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/common/atomic.hpp"
#include "duckdb/common/mutex.hpp"
#include "duckdb/common/unordered_map.hpp"
#include "duckdb/common/types/selection_vector.hpp"
#include "duckdb/common/types/vector.hpp"
#include "duckdb/planner/filter/prenest_filter_spec.hpp"
#include "duckdb/planner/table_filter.hpp"
#include "duckdb/planner/table_filter_state.hpp"

namespace duckdb {
class ClientContext;

//! The two counters that mean something per LIST column. With more than one list of a scan
//! pre-filtered, the totals in PrenestStats are sums over all of them, which is the right
//! number for "how much did the reader drop" but useless for "did THIS spec fire".
struct PrenestListStats {
	atomic<idx_t> elements_appended {0};
	atomic<idx_t> predicate_elements {0};
};

//! Instrumentation. Read with parquet_prenest_stat('<name>'); 'reset' zeroes. A name of the
//! form '<counter>:<list_name>' reads the per-list breakdown instead of the total.
struct PrenestStats {
	atomic<idx_t> elements_decoded {0};
	atomic<idx_t> elements_appended {0};
	atomic<idx_t> inner_iterations {0};
	atomic<idx_t> carryovers {0};
	atomic<idx_t> carryover_flattens {0};
	atomic<idx_t> predicate_elements {0};

	//! Stable accumulator for one list name. Entries are never erased - Reset() zeroes them in
	//! place - so a pointer handed to a reader stays valid for the life of the process.
	PrenestListStats &ForList(const string &list_name);
	//! Per-list counter, or 0 when that list was never filtered.
	idx_t GetListCounter(const string &list_name, const string &counter) const;

	void Reset() {
		elements_decoded = 0;
		elements_appended = 0;
		inner_iterations = 0;
		carryovers = 0;
		carryover_flattens = 0;
		predicate_elements = 0;
		ResetPerList();
	}
	static PrenestStats &Get();

private:
	void ResetPerList();

	mutable mutex list_lock;
	unordered_map<string, unique_ptr<PrenestListStats>> per_list;
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
	//! One "<field> <cmp> <literal>" term. The literal is still a string here -
	//! it is cast to the field's type in Bind(). Defined in the core planner so the
	//! optimizer can build these without depending on the parquet extension.
	using RawCondition = PrenestRawCondition;

public:
	//! Parse "list_name: f op v AND f op v ...". Returns nullptr for an empty spec.
	static unique_ptr<PrenestFilter> Parse(const string &spec);

	//! Build straight from conditions, bypassing the string spec. This is the path
	//! for predicates handed over by something other than the setting (e.g. an
	//! automatic extraction). Returns nullptr if `conditions` is empty.
	static unique_ptr<PrenestFilter> FromConditions(const string &list_name, vector<RawCondition> conditions);

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

	//! The LIST column this conjunction was written for.
	const string &ListName() const {
		return list_name;
	}
	//! The per-list accumulator for that column. Never null once the filter exists.
	//! get_mutable() because the accumulator is shared instrumentation, not part of the
	//! filter's own state - Apply() is const and still has to count.
	PrenestListStats &ListStats() const {
		return *list_stats.get_mutable();
	}

private:
	string list_name;
	optional_ptr<PrenestListStats> list_stats;
	vector<RawCondition> raw_conditions;
	vector<string> field_names;
	vector<idx_t> field_child_indexes;
	vector<PrenestCondition> conditions;
};

} // namespace duckdb
