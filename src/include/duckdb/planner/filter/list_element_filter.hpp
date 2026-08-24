//===----------------------------------------------------------------------===//
//                         DuckDB
//
// duckdb/planner/filter/list_element_filter.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/planner/table_filter.hpp"

namespace duckdb {

//! A filter on the elements of a LIST column. It means "some element of this list satisfies
//! child_filter", which is what a predicate absorbed into an UNNEST implies about the list column
//! feeding that UNNEST: a row whose elements all fail the predicate contributes no output row.
//!
//! This exists for pruning: when the element statistics of a storage segment show that no value in
//! it can pass child_filter, no row in the segment can contribute an element and the whole segment
//! can be skipped. It deliberately does NOT filter rows - deciding the predicate for one row means
//! running it over that row's elements, which the UNNEST above already does, so doing it here would
//! only duplicate that work. FilterSelection is therefore a no-op and only CheckStatistics works.
class ListElementFilter : public TableFilter {
public:
	static constexpr const TableFilterType TYPE = TableFilterType::LIST_ELEMENT;

public:
	explicit ListElementFilter(unique_ptr<TableFilter> child_filter);

	//! The filter that the list's elements are checked against
	unique_ptr<TableFilter> child_filter;

public:
	FilterPropagateResult CheckStatistics(BaseStatistics &stats) const override;
	string ToString(const string &column_name) const override;
	bool Equals(const TableFilter &other) const override;
	unique_ptr<TableFilter> Copy() const override;
	unique_ptr<Expression> ToExpression(const Expression &column) const override;
	void Serialize(Serializer &serializer) const override;
	static unique_ptr<TableFilter> Deserialize(Deserializer &deserializer);
};

} // namespace duckdb
