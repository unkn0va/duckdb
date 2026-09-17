#include "prenest_filter.hpp"

#include "column_reader.hpp"
#include "duckdb/common/string_util.hpp"
#include "duckdb/main/client_context.hpp"
#include "duckdb/planner/filter/constant_filter.hpp"
#include "duckdb/planner/table_filter_state.hpp"

namespace duckdb {

PrenestStats &PrenestStats::Get() {
	static PrenestStats stats;
	return stats;
}

PrenestListStats &PrenestStats::ForList(const string &list_name) {
	lock_guard<mutex> guard(list_lock);
	auto entry = per_list.find(list_name);
	if (entry == per_list.end()) {
		entry = per_list.insert(make_pair(list_name, make_uniq<PrenestListStats>())).first;
	}
	return *entry->second;
}

idx_t PrenestStats::GetListCounter(const string &list_name, const string &counter) const {
	lock_guard<mutex> guard(list_lock);
	auto entry = per_list.find(list_name);
	if (entry == per_list.end()) {
		return 0;
	}
	if (counter == "elements_appended") {
		return entry->second->elements_appended.load();
	}
	if (counter == "predicate_elements") {
		return entry->second->predicate_elements.load();
	}
	throw InvalidInputException("parquet_prenest_stat: \"%s\" has no per-list breakdown", counter);
}

void PrenestStats::ResetPerList() {
	lock_guard<mutex> guard(list_lock);
	// zeroed in place, never erased: readers cache the pointer ForList() hands out
	for (auto &entry : per_list) {
		entry.second->elements_appended = 0;
		entry.second->predicate_elements = 0;
	}
}

static bool ParseComparison(const string &term, string &field, ExpressionType &cmp, string &literal) {
	// order matters: the two-character operators must be tried first
	static const std::pair<const char *, ExpressionType> OPS[] = {
	    {">=", ExpressionType::COMPARE_GREATERTHANOREQUALTO},
	    {"<=", ExpressionType::COMPARE_LESSTHANOREQUALTO},
	    {"!=", ExpressionType::COMPARE_NOTEQUAL},
	    {">", ExpressionType::COMPARE_GREATERTHAN},
	    {"<", ExpressionType::COMPARE_LESSTHAN},
	    {"=", ExpressionType::COMPARE_EQUAL}};
	for (auto &op : OPS) {
		auto pos = term.find(op.first);
		if (pos == string::npos) {
			continue;
		}
		field = term.substr(0, pos);
		literal = term.substr(pos + strlen(op.first));
		StringUtil::Trim(field);
		StringUtil::Trim(literal);
		cmp = op.second;
		return !field.empty() && !literal.empty();
	}
	return false;
}

unique_ptr<PrenestFilter> PrenestFilter::FromConditions(const string &list_name, vector<RawCondition> conditions) {
	if (conditions.empty()) {
		return nullptr;
	}
	auto result = make_uniq<PrenestFilter>();
	result->list_name = list_name;
	StringUtil::Trim(result->list_name);
	result->list_stats = PrenestStats::Get().ForList(result->list_name);
	result->raw_conditions = std::move(conditions);
	for (auto &cond : result->raw_conditions) {
		bool seen = false;
		for (auto &name : result->field_names) {
			if (name == cond.field) {
				seen = true;
				break;
			}
		}
		if (!seen) {
			result->field_names.push_back(cond.field);
		}
	}
	return result;
}

bool PrenestFilter::ParseSpec(const string &spec, PrenestFilterSpec &result) {
	auto trimmed = spec;
	StringUtil::Trim(trimmed);
	if (trimmed.empty()) {
		return false;
	}
	auto colon = trimmed.find(':');
	if (colon == string::npos) {
		throw InvalidInputException("parquet_prenest_filter: expected \"<list>: <conjunction>\"");
	}
	auto list_name = trimmed.substr(0, colon);
	auto body = trimmed.substr(colon + 1);
	StringUtil::Trim(list_name);

	vector<RawCondition> conditions;
	for (auto &term_raw : StringUtil::Split(body, " AND ")) {
		auto term = term_raw;
		StringUtil::Trim(term);
		RawCondition cond;
		if (!ParseComparison(term, cond.field, cond.comparison, cond.literal)) {
			throw InvalidInputException("parquet_prenest_filter: cannot parse condition \"%s\"", term);
		}
		conditions.push_back(std::move(cond));
	}
	if (conditions.empty()) {
		throw InvalidInputException("parquet_prenest_filter: no conditions");
	}
	// left for the reader to resolve against the file schema - it may be a name or a path
	result.list_name = list_name;
	result.list_path = string();
	result.conditions = std::move(conditions);
	return true;
}

unique_ptr<PrenestFilter> PrenestFilter::FromSpec(const PrenestFilterSpec &spec) {
	return FromConditions(spec.list_name, spec.conditions);
}

bool PrenestFilter::Bind(ClientContext &context, const LogicalType &element_type) {
	if (element_type.id() != LogicalTypeId::STRUCT) {
		return false;
	}
	auto &children = StructType::GetChildTypes(element_type);
	conditions.clear();
	field_child_indexes.clear();

	for (auto &raw : raw_conditions) {
		optional_idx match;
		for (idx_t i = 0; i < children.size(); i++) {
			if (StringUtil::CIEquals(children[i].first, raw.field)) {
				match = i;
				break;
			}
		}
		if (!match.IsValid()) {
			return false;
		}
		auto &child_type = children[match.GetIndex()].second;
		Value constant;
		try {
			constant = Value(raw.literal).DefaultCastAs(child_type);
		} catch (std::exception &) {
			return false;
		}
		PrenestCondition cond;
		cond.child_idx = match.GetIndex();
		cond.filter = make_uniq<ConstantFilter>(raw.comparison, std::move(constant));
		cond.state = TableFilterState::Initialize(context, *cond.filter);
		conditions.push_back(std::move(cond));
		field_child_indexes.push_back(match.GetIndex());
	}
	return true;
}

idx_t PrenestFilter::Apply(Vector &element_vector, idx_t count, SelectionVector &sel, bool *keep) const {
	for (idx_t i = 0; i < count; i++) {
		sel.set_index(i, i);
	}
	idx_t approved = count;
	auto &entries = StructVector::GetEntries(element_vector);
	for (auto &cond : conditions) {
		if (approved == 0) {
			break;
		}
		auto &child = *entries[cond.child_idx];
		ColumnReader::ApplyFilter(child, *cond.filter, *cond.state, count, sel, approved);
	}
	memset(keep, 0, sizeof(bool) * count);
	for (idx_t i = 0; i < approved; i++) {
		keep[sel.get_index(i)] = true;
	}
	PrenestStats::Get().predicate_elements += count;
	ListStats().predicate_elements += count;
	return approved;
}

} // namespace duckdb
