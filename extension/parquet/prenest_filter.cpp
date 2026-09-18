#include "prenest_filter.hpp"

#include "column_reader.hpp"
#include "duckdb/common/string_util.hpp"
#include "duckdb/main/client_context.hpp"
#include "duckdb/planner/expression/bound_comparison_expression.hpp"
#include "duckdb/planner/expression/bound_conjunction_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/expression/bound_reference_expression.hpp"
#include "duckdb/planner/expression_iterator.hpp"

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
	if (spec.empty()) {
		return nullptr;
	}
	auto result = make_uniq<PrenestFilter>();
	result->list_name = spec.list_name;
	StringUtil::Trim(result->list_name);
	result->list_stats = PrenestStats::Get().ForList(result->list_name);
	// exactly one of the two is set: an injected predicate is already bound, the setting's
	// conditions are compiled into the same shape by Bind()
	result->raw_conditions = spec.conditions;
	result->injected_predicate = spec.predicate;
	return result;
}

unique_ptr<Expression> PrenestFilter::BuildPredicateFromConditions(const LogicalType &element_type) {
	// The setting speaks "<field> <op> <literal>"; the optimizer hands over an expression
	// directly. Compiling the former into the latter keeps one execution path instead of two.
	auto &children = StructType::GetChildTypes(element_type);
	vector<unique_ptr<Expression>> terms;
	for (auto &raw : raw_conditions) {
		optional_idx match;
		for (idx_t i = 0; i < children.size(); i++) {
			if (StringUtil::CIEquals(children[i].first, raw.field)) {
				match = i;
				break;
			}
		}
		if (!match.IsValid()) {
			return nullptr;
		}
		auto &child_type = children[match.GetIndex()].second;
		Value constant;
		try {
			constant = Value(raw.literal).DefaultCastAs(child_type);
		} catch (std::exception &) {
			return nullptr;
		}
		auto reference = make_uniq<BoundReferenceExpression>(raw.field, child_type, match.GetIndex());
		auto literal = make_uniq<BoundConstantExpression>(std::move(constant));
		terms.push_back(make_uniq<BoundComparisonExpression>(raw.comparison, std::move(reference),
		                                                     std::move(literal)));
	}
	if (terms.empty()) {
		return nullptr;
	}
	if (terms.size() == 1) {
		return std::move(terms[0]);
	}
	auto conjunction = make_uniq<BoundConjunctionExpression>(ExpressionType::CONJUNCTION_AND);
	for (auto &term : terms) {
		conjunction->children.push_back(std::move(term));
	}
	return std::move(conjunction);
}

//! Every BoundReferenceExpression index the predicate reads. These are positions in the element
//! struct - PrenestFilterPushdown::Flatten indexes them that way, and StructColumnReader always
//! materialises every child of the struct in that order, so no remapping is needed.
static void CollectReferencedIndexes(const Expression &expr, vector<idx_t> &result) {
	if (expr.GetExpressionClass() == ExpressionClass::BOUND_REF) {
		auto index = expr.Cast<BoundReferenceExpression>().index;
		for (auto existing : result) {
			if (existing == index) {
				return;
			}
		}
		result.push_back(index);
		return;
	}
	ExpressionIterator::EnumerateChildren(expr, [&](const Expression &child) {
		CollectReferencedIndexes(child, result);
	});
}

bool PrenestFilter::Bind(ClientContext &context, const LogicalType &element_type) {
	if (element_type.id() != LogicalTypeId::STRUCT) {
		return false;
	}
	auto &children = StructType::GetChildTypes(element_type);
	field_child_indexes.clear();
	predicate.reset();
	executor.reset();
	disabled = false;

	if (injected_predicate) {
		// the plan that built it is long gone by now, and each reader needs its own copy for
		// the executor to hold state against
		predicate = injected_predicate->Copy();
	} else {
		predicate = BuildPredicateFromConditions(element_type);
	}
	if (!predicate || predicate->return_type.id() != LogicalTypeId::BOOLEAN) {
		return false;
	}

	vector<idx_t> referenced;
	CollectReferencedIndexes(*predicate, referenced);
	if (referenced.empty()) {
		// nothing to read per element - a constant predicate is not worth a filtered read
		return false;
	}
	for (auto index : referenced) {
		if (index >= children.size()) {
			// the predicate was built against a different element struct
			return false;
		}
	}
	field_child_indexes = std::move(referenced);

	// the chunk mirrors the element struct one-to-one, so a BoundReferenceExpression index is
	// already the right column; unreferenced children cost nothing, they are only Referenced
	vector<LogicalType> chunk_types;
	for (auto &child : children) {
		chunk_types.push_back(child.second);
	}
	element_chunk.Destroy();
	element_chunk.InitializeEmpty(chunk_types);
	executor = make_uniq<ExpressionExecutor>(context, predicate.get());
	return true;
}

idx_t PrenestFilter::Apply(Vector &element_vector, idx_t count, SelectionVector &sel, bool *keep) {
	PrenestStats::Get().predicate_elements += count;
	ListStats().predicate_elements += count;

	if (!disabled) {
		auto &entries = StructVector::GetEntries(element_vector);
		if (entries.size() == element_chunk.ColumnCount()) {
			for (idx_t i = 0; i < entries.size(); i++) {
				element_chunk.data[i].Reference(*entries[i]);
			}
			element_chunk.SetCardinality(count);
			try {
				auto approved = executor->SelectExpression(element_chunk, sel);
				memset(keep, 0, sizeof(bool) * count);
				for (idx_t i = 0; i < approved; i++) {
					keep[sel.get_index(i)] = true;
				}
				return approved;
			} catch (std::exception &) {
				// The predicate threw on some element - a cast or a function that the Filter
				// above the UNNEST would only ever have seen for the rows it kept. Dropping the
				// pre-nest filter is always sound: the conjunct was never removed from that
				// Filter, so the rows are still filtered, just later.
				disabled = true;
			}
		} else {
			disabled = true;
		}
	}

	// keep everything
	for (idx_t i = 0; i < count; i++) {
		sel.set_index(i, i);
		keep[i] = true;
	}
	return count;
}

} // namespace duckdb
