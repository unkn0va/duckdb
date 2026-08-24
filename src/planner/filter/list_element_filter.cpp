#include "duckdb/planner/filter/list_element_filter.hpp"

#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/storage/statistics/base_statistics.hpp"
#include "duckdb/storage/statistics/list_stats.hpp"

namespace duckdb {

ListElementFilter::ListElementFilter(unique_ptr<TableFilter> child_filter_p)
    : TableFilter(TableFilterType::LIST_ELEMENT), child_filter(std::move(child_filter_p)) {
}

FilterPropagateResult ListElementFilter::CheckStatistics(BaseStatistics &stats) const {
	if (stats.GetType().id() != LogicalTypeId::LIST) {
		return FilterPropagateResult::NO_PRUNING_POSSIBLE;
	}
	auto &child_stats = ListStats::GetChildStats(stats);
	if (child_filter->CheckStatistics(child_stats) == FilterPropagateResult::FILTER_ALWAYS_FALSE) {
		// no element value in this segment can pass, so no row in it has a matching element
		return FilterPropagateResult::FILTER_ALWAYS_FALSE;
	}
	// The opposite direction does not carry over: even when every element value passes, a row whose
	// list is empty or NULL still has no element that does - so we can never report ALWAYS_TRUE.
	return FilterPropagateResult::NO_PRUNING_POSSIBLE;
}

string ListElementFilter::ToString(const string &column_name) const {
	return child_filter->ToString(column_name + "[*]");
}

bool ListElementFilter::Equals(const TableFilter &other_p) const {
	if (!TableFilter::Equals(other_p)) {
		return false;
	}
	auto &other = other_p.Cast<ListElementFilter>();
	return child_filter->Equals(*other.child_filter);
}

unique_ptr<TableFilter> ListElementFilter::Copy() const {
	return make_uniq<ListElementFilter>(child_filter->Copy());
}

unique_ptr<Expression> ListElementFilter::ToExpression(const Expression &column) const {
	// There is no scalar expression on the list column that reproduces this filter without running
	// the predicate per element, and this filter never claims to filter rows in the first place.
	// Returning a constant TRUE keeps consumers that materialise filters as expressions correct.
	return make_uniq<BoundConstantExpression>(Value::BOOLEAN(true));
}

} // namespace duckdb
