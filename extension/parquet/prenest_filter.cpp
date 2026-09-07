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

unique_ptr<PrenestFilter> PrenestFilter::Parse(const string &spec) {
	auto trimmed = spec;
	StringUtil::Trim(trimmed);
	if (trimmed.empty()) {
		return nullptr;
	}
	auto result = make_uniq<PrenestFilter>();
	auto colon = trimmed.find(':');
	if (colon == string::npos) {
		throw InvalidInputException("parquet_prenest_filter: expected \"<list_name>: <conjunction>\"");
	}
	result->list_name = trimmed.substr(0, colon);
	StringUtil::Trim(result->list_name);
	auto body = trimmed.substr(colon + 1);

	for (auto &term_raw : StringUtil::Split(body, " AND ")) {
		auto term = term_raw;
		StringUtil::Trim(term);
		RawCondition cond;
		if (!ParseComparison(term, cond.field, cond.comparison, cond.literal)) {
			throw InvalidInputException("parquet_prenest_filter: cannot parse condition \"%s\"", term);
		}
		result->raw_conditions.push_back(std::move(cond));
	}
	if (result->raw_conditions.empty()) {
		throw InvalidInputException("parquet_prenest_filter: no conditions");
	}
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
	return approved;
}

} // namespace duckdb
