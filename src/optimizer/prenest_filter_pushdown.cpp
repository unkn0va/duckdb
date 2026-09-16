#include "duckdb/optimizer/prenest_filter_pushdown.hpp"

#include "duckdb/planner/column_binding_map.hpp"
#include "duckdb/common/string_util.hpp"
#include "duckdb/main/client_context.hpp"
#include "duckdb/optimizer/remove_unused_columns.hpp"
#include "duckdb/planner/expression/bound_between_expression.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_comparison_expression.hpp"
#include "duckdb/planner/expression/bound_conjunction_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/expression/bound_unnest_expression.hpp"
#include "duckdb/planner/filter/prenest_filter_spec.hpp"
#include "duckdb/planner/logical_operator_visitor.hpp"
#include "duckdb/planner/operator/logical_filter.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/planner/operator/logical_projection.hpp"
#include "duckdb/planner/operator/logical_unnest.hpp"

namespace duckdb {


namespace {

//! One step of the access path from a scan's root column down to the filtered
//! element: either "descend into the LIST element" or "take struct field <name>".
struct PrenestPathEntry {
	bool element;
	string name;

	bool operator==(const PrenestPathEntry &other) const {
		return element == other.element && (element || StringUtil::CIEquals(name, other.name));
	}
};

//! Counts how often each ColumnBinding is referenced anywhere in the plan.
//! A list we intend to truncate must be consumed by nothing but the UNNEST chain
//! we followed - anything else would observe the dropped elements.
class BindingUseCounter : public LogicalOperatorVisitor {
public:
	column_binding_map_t<idx_t> counts;

protected:
	unique_ptr<Expression> VisitReplace(BoundColumnRefExpression &expr, unique_ptr<Expression> *expr_ptr) override {
		counts[expr.binding]++;
		return nullptr;
	}
};

//! Reduces a struct-extract chain to (column reference, field names). Reuses
//! BaseColumnPruner::HandleExtractRecursive so a get_field chain is interpreted
//! exactly the way the nested-projection column pruner interprets it.
class ExtractChainReducer : public BaseColumnPruner {
public:
	//! Returns false unless `expr` is a plain column reference or a pure chain of
	//! struct field accesses on one.
	bool Reduce(unique_ptr<Expression> &expr, ColumnBinding &binding, vector<string> &field_path,
	            LogicalType &leaf_type) {
		if (expr->GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
			auto &ref = expr->Cast<BoundColumnRefExpression>();
			binding = ref.binding;
			leaf_type = ref.return_type;
			return true;
		}
		optional_ptr<BoundColumnRefExpression> colref;
		vector<ReferencedExtractComponent> components;
		ColumnIndex root(0);
		reference<ColumnIndex> path_ref(root);
		if (!HandleExtractRecursive(expr, colref, path_ref, components)) {
			return false;
		}
		if (!colref || root.ChildIndexCount() != 1) {
			return false;
		}
		binding = colref->binding;
		return IndexPathToNames(colref->return_type, root.GetChildIndex(0), field_path, leaf_type);
	}

private:
	//! Translate the index path produced by the pruner into field names. Anything
	//! that is not a plain STRUCT field access along the way (a VARIANT extract,
	//! for instance) makes this fail, which keeps such chains out of the probe.
	static bool IndexPathToNames(const LogicalType &root_type, const ColumnIndex &path, vector<string> &names,
	                             LogicalType &leaf_type) {
		reference<const ColumnIndex> current(path);
		auto type = root_type;
		while (true) {
			if (type.id() != LogicalTypeId::STRUCT || !current.get().HasPrimaryIndex()) {
				return false;
			}
			auto &children = StructType::GetChildTypes(type);
			auto index = current.get().GetPrimaryIndex();
			if (index >= children.size()) {
				return false;
			}
			names.push_back(children[index].first);
			type = children[index].second;
			auto &child_indexes = current.get().GetChildIndexes();
			if (child_indexes.empty()) {
				break;
			}
			if (child_indexes.size() != 1) {
				return false;
			}
			current = child_indexes[0];
		}
		leaf_type = std::move(type);
		return true;
	}
};

//! A single extracted conjunct together with the scan and LIST it belongs to.
struct PrenestCandidate {
	optional_ptr<LogicalGet> get;
	//! Path from the scan's root column down to and including the LIST. Used as the
	//! identity of the list, so two different lists never get merged by leaf name.
	vector<PrenestPathEntry> list_path;
	string list_name;
	PrenestRawCondition condition;
};

bool IsSupportedComparison(ExpressionType type) {
	// NOTE: the DISTINCT FROM variants are excluded on purpose - the reader builds a
	// ConstantFilter, whose NULL handling does not match them.
	switch (type) {
	case ExpressionType::COMPARE_EQUAL:
	case ExpressionType::COMPARE_NOTEQUAL:
	case ExpressionType::COMPARE_LESSTHAN:
	case ExpressionType::COMPARE_GREATERTHAN:
	case ExpressionType::COMPARE_LESSTHANOREQUALTO:
	case ExpressionType::COMPARE_GREATERTHANOREQUALTO:
		return true;
	default:
		return false;
	}
}

//! Only values whose string form is understood again by Value::DefaultCastAs are
//! pushed - the literal travels to the reader as a string.
bool IsSupportedLiteralType(const LogicalType &type) {
	if (type.IsNested() || type.HasAlias()) {
		return false;
	}
	switch (type.id()) {
	case LogicalTypeId::BOOLEAN:
	case LogicalTypeId::TINYINT:
	case LogicalTypeId::SMALLINT:
	case LogicalTypeId::INTEGER:
	case LogicalTypeId::BIGINT:
	case LogicalTypeId::HUGEINT:
	case LogicalTypeId::UTINYINT:
	case LogicalTypeId::USMALLINT:
	case LogicalTypeId::UINTEGER:
	case LogicalTypeId::UBIGINT:
	case LogicalTypeId::UHUGEINT:
	case LogicalTypeId::FLOAT:
	case LogicalTypeId::DOUBLE:
	case LogicalTypeId::DECIMAL:
	case LogicalTypeId::VARCHAR:
	case LogicalTypeId::DATE:
	case LogicalTypeId::TIME:
	case LogicalTypeId::TIMESTAMP:
	case LogicalTypeId::TIMESTAMP_SEC:
	case LogicalTypeId::TIMESTAMP_MS:
	case LogicalTypeId::TIMESTAMP_NS:
		return true;
	default:
		return false;
	}
}

class PrenestFilterExtractor {
public:
	explicit PrenestFilterExtractor(ClientContext &context) : context(context) {
	}

	void Run(LogicalOperator &plan) {
		CollectOperators(plan);
		BindingUseCounter counter;
		counter.VisitOperator(plan);
		use_counts = std::move(counter.counts);

		vector<PrenestCandidate> candidates;
		CollectCandidates(plan, candidates);
		Apply(candidates);
	}

private:
	//! Index every operator that can define a binding we need to walk through.
	//! A table index that shows up twice is treated as unusable rather than guessed at.
	void CollectOperators(LogicalOperator &op) {
		optional_idx table_index;
		switch (op.type) {
		case LogicalOperatorType::LOGICAL_PROJECTION:
			table_index = op.Cast<LogicalProjection>().table_index;
			break;
		case LogicalOperatorType::LOGICAL_UNNEST:
			table_index = op.Cast<LogicalUnnest>().unnest_index;
			break;
		case LogicalOperatorType::LOGICAL_GET:
			table_index = op.Cast<LogicalGet>().table_index;
			break;
		default:
			break;
		}
		if (table_index.IsValid()) {
			auto entry = operators.find(table_index.GetIndex());
			if (entry == operators.end()) {
				operators.insert(make_pair(table_index.GetIndex(), reference<LogicalOperator>(op)));
			} else {
				ambiguous_indexes.insert(table_index.GetIndex());
			}
		}
		for (auto &child : op.children) {
			CollectOperators(*child);
		}
	}

	void CollectCandidates(LogicalOperator &op, vector<PrenestCandidate> &result) {
		if (op.type == LogicalOperatorType::LOGICAL_FILTER) {
			for (auto &expr : op.expressions) {
				TryExtractConjunct(expr, result);
			}
		}
		for (auto &child : op.children) {
			CollectCandidates(*child, result);
		}
	}

	void TryExtractConjunct(unique_ptr<Expression> &expr, vector<PrenestCandidate> &result) {
		switch (expr->GetExpressionClass()) {
		case ExpressionClass::BOUND_CONJUNCTION: {
			auto &conj = expr->Cast<BoundConjunctionExpression>();
			if (conj.GetExpressionType() != ExpressionType::CONJUNCTION_AND) {
				return;
			}
			for (auto &child : conj.children) {
				TryExtractConjunct(child, result);
			}
			return;
		}
		case ExpressionClass::BOUND_COMPARISON: {
			auto &cmp = expr->Cast<BoundComparisonExpression>();
			auto type = cmp.GetExpressionType();
			if (!IsSupportedComparison(type)) {
				return;
			}
			if (TryBuildCondition(cmp.left, *cmp.right, type, result)) {
				return;
			}
			TryBuildCondition(cmp.right, *cmp.left, FlipComparisonExpression(type), result);
			return;
		}
		case ExpressionClass::BOUND_BETWEEN: {
			// x BETWEEN a AND b is x >= a AND x <= b; both halves reject a NULL x just
			// like BETWEEN does. Pushing only one half is still correct because the
			// original conjunct stays in the FILTER.
			auto &between = expr->Cast<BoundBetweenExpression>();
			TryBuildCondition(between.input, *between.lower, between.LowerComparisonType(), result);
			TryBuildCondition(between.input, *between.upper, between.UpperComparisonType(), result);
			return;
		}
		default:
			return;
		}
	}

	//! `chain` must reduce to a struct field of an unnested element and `constant`
	//! must be a bound constant of exactly that field's type.
	bool TryBuildCondition(unique_ptr<Expression> &chain, Expression &constant, ExpressionType comparison,
	                       vector<PrenestCandidate> &result) {
		if (!IsSupportedComparison(comparison) || constant.GetExpressionClass() != ExpressionClass::BOUND_CONSTANT) {
			return false;
		}
		auto &value = constant.Cast<BoundConstantExpression>().value;
		if (value.IsNull()) {
			// comparing against NULL is never a plain ConstantFilter
			return false;
		}
		ExtractChainReducer reducer;
		ColumnBinding binding;
		vector<string> field_path;
		LogicalType leaf_type;
		if (!reducer.Reduce(chain, binding, field_path, leaf_type)) {
			return false;
		}
		if (field_path.empty()) {
			// the whole element compared against a constant - not a field predicate
			return false;
		}
		// A cast between the extract and the comparison would mean the comparison happens
		// at a type other than the field's, while the reader casts the literal to the
		// FIELD type. Requiring an exact type match rules that out.
		if (!IsSupportedLiteralType(leaf_type) || value.type() != leaf_type) {
			return false;
		}

		PrenestCandidate candidate;
		vector<PrenestPathEntry> path;
		for (auto &name : field_path) {
			path.push_back(PrenestPathEntry {false, name});
		}
		if (!ResolveToScan(binding, std::move(path), candidate)) {
			return false;
		}
		candidate.condition.field = field_path.back();
		candidate.condition.comparison = comparison;
		candidate.condition.literal = value.ToString();
		result.push_back(std::move(candidate));
		return true;
	}

	//! Walk `binding` down through UNNEST/PROJECTION until it lands on a scan,
	//! accumulating the access path as we go.
	bool ResolveToScan(ColumnBinding binding, vector<PrenestPathEntry> path, PrenestCandidate &candidate) {
		ExtractChainReducer reducer;
		for (idx_t guard = 0; guard < MAX_RESOLVE_DEPTH; guard++) {
			if (ambiguous_indexes.find(binding.table_index) != ambiguous_indexes.end()) {
				return false;
			}
			auto entry = operators.find(binding.table_index);
			if (entry == operators.end()) {
				return false;
			}
			auto &op = entry->second.get();
			if (op.type == LogicalOperatorType::LOGICAL_GET) {
				return FinishAtScan(op.Cast<LogicalGet>(), binding, path, candidate);
			}

			optional_ptr<unique_ptr<Expression>> source;
			bool through_unnest = false;
			if (op.type == LogicalOperatorType::LOGICAL_PROJECTION) {
				auto &proj = op.Cast<LogicalProjection>();
				if (binding.column_index >= proj.expressions.size()) {
					return false;
				}
				source = proj.expressions[binding.column_index];
			} else if (op.type == LogicalOperatorType::LOGICAL_UNNEST) {
				auto &unnest = op.Cast<LogicalUnnest>();
				if (binding.column_index >= unnest.expressions.size()) {
					return false;
				}
				auto &expr = unnest.expressions[binding.column_index];
				if (expr->GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
					return false;
				}
				source = expr->Cast<BoundUnnestExpression>().child;
				through_unnest = true;
			} else {
				// anything else (joins, aggregates, ...) is not something we follow
				return false;
			}

			ColumnBinding next;
			vector<string> prefix;
			LogicalType prefix_type;
			if (!reducer.Reduce(*source, next, prefix, prefix_type)) {
				return false;
			}
			vector<PrenestPathEntry> new_path;
			for (auto &name : prefix) {
				new_path.push_back(PrenestPathEntry {false, name});
			}
			if (through_unnest) {
				new_path.push_back(PrenestPathEntry {true, string()});
			}
			for (auto &step : path) {
				new_path.push_back(step);
			}
			path = std::move(new_path);
			binding = next;
			// Everything below the element we filter on carries the list we are about to
			// truncate. If anything else in the plan reads it, the truncation would be
			// visible there too, so refuse unless this is its only use.
			auto use = use_counts.find(binding);
			if (use == use_counts.end() || use->second != 1) {
				return false;
			}
		}
		return false;
	}

	bool FinishAtScan(LogicalGet &get, ColumnBinding binding, vector<PrenestPathEntry> &path,
	                  PrenestCandidate &candidate) {
		auto &column_ids = get.GetColumnIds();
		if (binding.column_index >= column_ids.size()) {
			return false;
		}
		auto &root = column_ids[binding.column_index];
		if (!root.HasPrimaryIndex()) {
			return false;
		}
		auto root_index = root.GetPrimaryIndex();
		if (root_index >= get.names.size() || root_index >= get.returned_types.size()) {
			// virtual column (row id, file row number, ...)
			return false;
		}
		path.insert(path.begin(), PrenestPathEntry {false, get.names[root_index]});

		// the path has to end as: ... -> <LIST field> -> element -> <leaf field>
		if (path.size() < 3) {
			return false;
		}
		auto &leaf = path[path.size() - 1];
		auto &element = path[path.size() - 2];
		auto &list = path[path.size() - 3];
		if (leaf.element || !element.element || list.element) {
			return false;
		}
		if (!ValidatePath(get.returned_types[root_index], path)) {
			return false;
		}
		candidate.get = get;
		candidate.list_name = list.name;
		candidate.list_path.assign(path.begin(), path.end() - 2);
		return true;
	}

	//! Replay the path against the scan's real type. This is what rules out a path
	//! that was reduced wrongly - Bind() on the reader side would silently do nothing.
	static bool ValidatePath(const LogicalType &root_type, const vector<PrenestPathEntry> &path) {
		auto type = root_type;
		for (idx_t i = 1; i < path.size(); i++) {
			auto &step = path[i];
			if (step.element) {
				if (type.id() != LogicalTypeId::LIST) {
					return false;
				}
				type = ListType::GetChildType(type);
				continue;
			}
			if (type.id() != LogicalTypeId::STRUCT) {
				return false;
			}
			auto &children = StructType::GetChildTypes(type);
			optional_idx match;
			for (idx_t c = 0; c < children.size(); c++) {
				if (StringUtil::CIEquals(children[c].first, step.name)) {
					match = c;
					break;
				}
			}
			if (!match.IsValid()) {
				return false;
			}
			type = children[match.GetIndex()].second;
		}
		return true;
	}

	//! One spec per scan. The probe only supports a single list, so when conjuncts
	//! land on different lists the one with the most conjuncts wins.
	void Apply(const vector<PrenestCandidate> &candidates) {
		struct Group {
			optional_ptr<LogicalGet> get;
			vector<PrenestPathEntry> list_path;
			string list_name;
			vector<PrenestRawCondition> conditions;
		};
		vector<Group> groups;
		for (auto &candidate : candidates) {
			bool found = false;
			for (auto &group : groups) {
				if (group.get.get() == candidate.get.get() && group.list_path == candidate.list_path) {
					group.conditions.push_back(candidate.condition);
					found = true;
					break;
				}
			}
			if (!found) {
				Group group;
				group.get = candidate.get;
				group.list_path = candidate.list_path;
				group.list_name = candidate.list_name;
				group.conditions.push_back(candidate.condition);
				groups.push_back(std::move(group));
			}
		}

		unordered_map<LogicalGet *, idx_t> best;
		for (idx_t i = 0; i < groups.size(); i++) {
			auto key = groups[i].get.get();
			auto entry = best.find(key);
			if (entry == best.end() || groups[i].conditions.size() > groups[entry->second].conditions.size()) {
				best[key] = i;
			}
		}
		for (auto &entry : best) {
			auto &group = groups[entry.second];
			if (!group.get->bind_data) {
				continue;
			}
			PrenestFilterSpec spec;
			spec.list_name = group.list_name;
			spec.conditions = group.conditions;
			group.get->bind_data->TrySetPrenestFilter(spec);
		}
	}

private:
	static constexpr idx_t MAX_RESOLVE_DEPTH = 64;

	ClientContext &context;
	unordered_map<idx_t, reference<LogicalOperator>> operators;
	unordered_set<idx_t> ambiguous_indexes;
	column_binding_map_t<idx_t> use_counts;
};

} // namespace

void PrenestFilterPushdown::Optimize(LogicalOperator &plan) {
	Value enabled;
	if (!context.TryGetCurrentSetting("parquet_prenest_auto", enabled)) {
		// the setting only exists once the parquet extension is loaded
		return;
	}
	if (enabled.IsNull() || !BooleanValue::Get(enabled)) {
		return;
	}
	PrenestFilterExtractor extractor(context);
	extractor.Run(plan);
}

} // namespace duckdb
