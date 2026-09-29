//===----------------------------------------------------------------------===//
//                         DuckDB
//
// duckdb/optimizer/prenest_filter_pushdown.hpp
//
// PROBE CODE. A port of DataFusion's nested filter pushdown (shallow paradigm).
//
// A Filter sitting on an UNNEST has its conjuncts split three ways -
// comprehensions / binders / passthroughs - and a binder over the unnested
// element is re-expressed as a BoundComprehensionExpression bound to that
// UNNEST's list. Comprehensions that reach a scan become a PrenestFilterSpec so
// the reader can drop elements before the list is assembled; the rest are rolled
// up into LogicalUnnest::filters, where nothing consumes them yet.
//
// One spec is produced per LIST column of a scan, grouped by the exact root-relative path
// of the list (DataFusion groups by a fingerprint of the parent element struct's field
// names; the path is a strict refinement of that). Predicates naming the same list are
// AND-combined; each spec is safety-checked on its own, so an unsafe or inexpressible list
// costs only itself.
//
// The binder is never removed from the Filter it came from, so the rule only ever
// ADDS information: a mis-pushed predicate costs performance, never correctness.
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/common/atomic.hpp"
#include "duckdb/planner/logical_operator.hpp"

namespace duckdb {
class ClientContext;

//! Where the comprehensions of the last optimized plan ended up. Measurement only.
struct PrenestPushdownStats {
	//! binders turned into a comprehension
	idx_t comprehensions_formed = 0;
	//! binders that could not be expressed as one
	idx_t binders_not_formable = 0;
	//! conjuncts unrelated to the UNNEST they sat on
	idx_t passthroughs = 0;
	//! comprehensions wrapped in a generator level to pass an outer UNNEST (Recurse)
	idx_t levels_lifted = 0;
	//! scans that received at least one PrenestFilterSpec
	idx_t absorbed_at_scan = 0;
	//! specs handed to a scan in total - one per LIST column, so >= absorbed_at_scan
	idx_t specs_pushed = 0;
	//! comprehensions lifted onto LogicalUnnest::filters
	idx_t rolled_up = 0;
	//! comprehensions that reached a scan but whose list is read elsewhere too
	idx_t refused_list_read_elsewhere = 0;
	//! comprehensions nothing claimed - dropped, which is always safe
	idx_t dropped = 0;
};

//! Process-global totals. PrenestPushdownStats is one run's worth and is returned by value;
//! these are atomic and only ever ADDED to, which is what lets a plain SELECT read them: that
//! SELECT's own run of the pass contributes zero, so the numbers survive being looked at. The
//! whole-struct assignment this replaced did not - reading with the pass enabled overwrote the
//! values with the reading query's own zeros, and the workaround was to turn the pass off first.
//! Zeroed by parquet_prenest_stat('reset').
struct PrenestPushdownTotals {
	atomic<idx_t> comprehensions_formed {0};
	atomic<idx_t> binders_not_formable {0};
	atomic<idx_t> passthroughs {0};
	atomic<idx_t> levels_lifted {0};
	atomic<idx_t> absorbed_at_scan {0};
	atomic<idx_t> specs_pushed {0};
	atomic<idx_t> rolled_up {0};
	atomic<idx_t> refused_list_read_elsewhere {0};
	atomic<idx_t> dropped {0};

	DUCKDB_API void Add(const PrenestPushdownStats &run);
	DUCKDB_API void Reset();
	//! Named read. Throws on an unknown name rather than answering 0, because unlike the
	//! per-list counters there is no "this one was never registered" case to be lenient about.
	DUCKDB_API idx_t Get(const string &name) const;

	DUCKDB_API static PrenestPushdownTotals &GetTotals();
};

class PrenestFilterPushdown {
public:
	explicit PrenestFilterPushdown(ClientContext &context) : context(context) {
	}

	//! Does nothing unless `parquet_prenest_auto` is set.
	void Optimize(unique_ptr<LogicalOperator> &plan);

private:
	ClientContext &context;
};

} // namespace duckdb
