//===----------------------------------------------------------------------===//
//                         DuckDB
//
// duckdb/optimizer/nested_filter_pushdown.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/common/common.hpp"

namespace duckdb {
class LogicalOperator;

//! Turns predicates that filter pushdown absorbed into an UNNEST (LogicalUnnest::element_filters)
//! into pruning filters on the scan that feeds the unnested list.
//!
//! Absorbing such a predicate stops the failing elements from being expanded, but the scan below
//! still reads every row group of the list column. The predicate does say something about the scan
//! though: a row whose elements all fail it contributes no output row at all, so a storage segment
//! whose element statistics show that no value in it can pass can be skipped entirely. That is
//! expressed as a ListElementFilter on the scan column - a filter that only ever prunes and never
//! removes rows (see ListElementFilter).
//!
//! Both directions of the reasoning are deliberately conservative:
//!  - a predicate is translated only when it is a comparison (or an AND/OR/BETWEEN of comparisons)
//!    between a field of the element and a constant. Anything else is skipped, which costs nothing.
//!  - the list is traced from the UNNEST to its scan only through operators that map their rows
//!    one-to-one onto the scan's rows (UNNEST, PROJECTION, FILTER). If a join or an aggregate sits
//!    in between, this pass gives up rather than reason about which rows a pruned segment removes.
//!
//! Runs after RemoveUnusedColumns, since the filters are keyed by the scan's final column ids.
class NestedFilterPushdown {
public:
	void Optimize(LogicalOperator &op);
};

} // namespace duckdb
