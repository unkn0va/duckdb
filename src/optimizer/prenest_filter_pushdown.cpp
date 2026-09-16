#include "duckdb/optimizer/prenest_filter_pushdown.hpp"

#include "duckdb/common/string_util.hpp"
#include "duckdb/main/client_context.hpp"
#include "duckdb/optimizer/remove_unused_columns.hpp"
#include "duckdb/planner/column_binding_map.hpp"
#include "duckdb/planner/expression/bound_between_expression.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_comparison_expression.hpp"
#include "duckdb/planner/expression/bound_comprehension_expression.hpp"
#include "duckdb/planner/expression/bound_conjunction_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/expression/bound_reference_expression.hpp"
#include "duckdb/planner/expression/bound_unnest_expression.hpp"
#include "duckdb/planner/expression_iterator.hpp"
#include "duckdb/planner/filter/prenest_filter_spec.hpp"
#include "duckdb/planner/logical_operator_visitor.hpp"
#include "duckdb/planner/operator/logical_filter.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/planner/operator/logical_projection.hpp"
#include "duckdb/planner/operator/logical_unnest.hpp"

namespace duckdb {

namespace {

//! One step of the access path from a scan's root column down to a list or field:
//! either "descend into the LIST element" or "take struct field <name>".
struct PrenestPathEntry {
	bool element;
	string name;
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

//! Whether an expression means anything when evaluated against a single list element.
//! Adapted from CanEvaluateOnElement in the pushdown_unnest.cpp removed in fff6e6276e:
//! subqueries, window and aggregate expressions have no per-element meaning, and a volatile
//! function would be evaluated over a different set of values than it is today.
bool IsElementEvaluable(const Expression &expr) {
	switch (expr.GetExpressionClass()) {
	case ExpressionClass::BOUND_BETWEEN:
	case ExpressionClass::BOUND_CASE:
	case ExpressionClass::BOUND_CAST:
	case ExpressionClass::BOUND_COLUMN_REF:
	case ExpressionClass::BOUND_COMPARISON:
	case ExpressionClass::BOUND_CONJUNCTION:
	case ExpressionClass::BOUND_CONSTANT:
	case ExpressionClass::BOUND_FUNCTION:
	case ExpressionClass::BOUND_OPERATOR:
	case ExpressionClass::BOUND_REF:
		break;
	default:
		// BOUND_SUBQUERY, BOUND_WINDOW, BOUND_AGGREGATE, BOUND_LAMBDA, BOUND_PARAMETER, ...
		return false;
	}
	if (expr.IsVolatile()) {
		return false;
	}
	auto evaluable = true;
	ExpressionIterator::EnumerateChildren(expr, [&](const Expression &child) {
		if (!IsElementEvaluable(child)) {
			evaluable = false;
		}
	});
	return evaluable;
}

bool FindStructChild(const LogicalType &struct_type, const string &name, idx_t &result) {
	if (struct_type.id() != LogicalTypeId::STRUCT) {
		return false;
	}
	auto &children = StructType::GetChildTypes(struct_type);
	for (idx_t i = 0; i < children.size(); i++) {
		if (StringUtil::CIEquals(children[i].first, name)) {
			result = i;
			return true;
		}
	}
	return false;
}

//! Counts how often one specific ColumnBinding is referenced across a plan.
class BindingUseCounter : public LogicalOperatorVisitor {
public:
	explicit BindingUseCounter(ColumnBinding target_p) : target(target_p) {
	}
	ColumnBinding target;
	idx_t count = 0;

protected:
	unique_ptr<Expression> VisitReplace(BoundColumnRefExpression &expr, unique_ptr<Expression> *expr_ptr) override {
		if (expr.binding == target) {
			count++;
		}
		return nullptr;
	}
};

bool ReferencesUnnest(const Expression &expr, idx_t unnest_index) {
	if (expr.GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
		return expr.Cast<BoundColumnRefExpression>().binding.table_index == unnest_index;
	}
	auto found = false;
	ExpressionIterator::EnumerateChildren(expr, [&](const Expression &child) {
		if (ReferencesUnnest(child, unnest_index)) {
			found = true;
		}
	});
	return found;
}

bool HasColumnRef(const Expression &expr) {
	if (expr.GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
		return true;
	}
	auto found = false;
	ExpressionIterator::EnumerateChildren(expr, [&](const Expression &child) {
		if (HasColumnRef(child)) {
			found = true;
		}
	});
	return found;
}

string LastSegment(const string &source) {
	auto pos = source.rfind('.');
	return pos == string::npos ? source : source.substr(pos + 1);
}

//! "c_orders" / "c_orders.o_lineitems" - the element steps are implicit between fields.
string RenderPath(const vector<PrenestPathEntry> &path) {
	string result;
	for (auto &step : path) {
		if (step.element) {
			continue;
		}
		if (!result.empty()) {
			result += ".";
		}
		result += step.name;
	}
	return result;
}

//===--------------------------------------------------------------------===//
// Extractor
//===--------------------------------------------------------------------===//
class PrenestFilterExtractor {
public:
	explicit PrenestFilterExtractor(ClientContext &context_p) : context(context_p) {
	}

	PrenestPushdownStats Run(unique_ptr<LogicalOperator> &plan) {
		root = plan.get();
		CollectOperators(*plan);
		FormComprehensions(plan);
		AbsorbAtScan(plan);
		RollUp(plan);
		StripLeftovers(plan);
		return stats;
	}

private:
	//===------------------------------------------------------------------===//
	// Pass 1 - three-way classification at a Filter sitting on an UNNEST
	//===------------------------------------------------------------------===//
	void FormComprehensions(unique_ptr<LogicalOperator> &op) {
		for (auto &child : op->children) {
			FormComprehensions(child);
		}
		if (op->type != LogicalOperatorType::LOGICAL_FILTER || op->children.empty() ||
		    op->children[0]->type != LogicalOperatorType::LOGICAL_UNNEST) {
			return;
		}
		auto &unnest = op->children[0]->Cast<LogicalUnnest>();

		// Classify each conjunct of the Filter into one of three buckets:
		//   comprehensions - already a BoundComprehensionExpression, from a deeper UNNEST
		//   binders        - predicates referencing THIS UNNEST's output element
		//   passthroughs   - predicates with no relation to this UNNEST
		vector<reference<Expression>> binders;
		for (auto &expr : op->expressions) {
			if (expr->GetExpressionClass() == ExpressionClass::BOUND_COMPREHENSION) {
				// Incoming comprehensions stay above this UNNEST: this is the SHALLOW
				// paradigm, where the roll-up lifts them into the UNNEST that formed them.
				// Wrapping them in a Recurse and pushing them further down is the deep
				// paradigm, which is out of scope here.
				stats.comprehensions_left_above++;
			} else if (ReferencesUnnest(*expr, unnest.unnest_index)) {
				binders.push_back(*expr);
			} else {
				// A passthrough could move below the UNNEST, but FilterPushdown has already
				// placed it; moving it again would only duplicate that work. Classifying it
				// is what matters - it is not a binder, so it never blocks comprehension
				// formation. That is what replaces the old plan-wide use counter.
				stats.passthroughs++;
			}
		}
		if (binders.empty()) {
			return;
		}

		// Is this UNNEST shaped like a comprehension binder? Exactly one list to iterate, so
		// the binder is unambiguous. (DuckDB has no struct-unnest inside LogicalUnnest - UNNEST
		// over a STRUCT is expanded by the binder - so the LIST check covers both of
		// DataFusion's `can_form_comprehension` conditions.)
		if (unnest.expressions.size() != 1 ||
		    unnest.expressions[0]->GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
			stats.binders_not_formable += binders.size();
			return;
		}
		auto &bound_unnest = unnest.expressions[0]->Cast<BoundUnnestExpression>();
		if (bound_unnest.child->return_type.id() != LogicalTypeId::LIST) {
			stats.binders_not_formable += binders.size();
			return;
		}
		auto element_type = ListType::GetChildType(bound_unnest.child->return_type);

		// The clean dotted name of the list this UNNEST iterates, relative to the scan root.
		// This becomes the `source` of every comprehension formed here.
		string source;
		if (!ResolveSource(unnest, source)) {
			stats.binders_not_formable += binders.size();
			return;
		}

		vector<unique_ptr<Expression>> formed;
		for (auto &binder : binders) {
			auto flat = Flatten(binder.get(), ColumnBinding(unnest.unnest_index, 0), element_type);
			if (!flat) {
				stats.binders_not_formable++;
				continue;
			}
			formed.push_back(make_uniq<BoundComprehensionExpression>(source, std::move(flat)));
			stats.comprehensions_formed++;
		}
		if (formed.empty()) {
			return;
		}
		// The binder itself is deliberately NOT removed from the Filter above. DataFusion moves
		// it, because it has a Filtered UNNEST operator to consume the comprehension; with no
		// consumer the predicate would simply be lost. Leaving it in place makes the whole rule
		// additive - whatever becomes of the comprehension below, the rows are still filtered
		// here - so a mis-pushed predicate costs performance, never correctness.
		auto filter = make_uniq<LogicalFilter>();
		filter->expressions = std::move(formed);
		filter->children.push_back(std::move(unnest.children[0]));
		filter->ResolveOperatorTypes();
		unnest.children[0] = std::move(filter);
	}

	//! Rewrite `expr` so the element's fields are referenced directly instead of through
	//! struct_extract chains: `struct_extract(l, 'l_quantity') < 24` becomes `#l_quantity < 24`,
	//! the reference indexed by position in the element struct. Returns nullptr when the
	//! predicate cannot be evaluated against one element alone.
	unique_ptr<Expression> Flatten(const Expression &expr, ColumnBinding element_binding,
	                               const LogicalType &element_type) {
		if (!IsElementEvaluable(expr)) {
			return nullptr;
		}
		auto copy = expr.Copy();
		auto failed = false;
		FlattenInPlace(copy, element_binding, element_type, failed);
		if (failed || !copy) {
			return nullptr;
		}
		// Anything still referencing a column refers to something other than this element (a
		// column of the child plan, a correlated reference) and is not available per element.
		if (HasColumnRef(*copy)) {
			return nullptr;
		}
		return copy;
	}

	void FlattenInPlace(unique_ptr<Expression> &expr, ColumnBinding element_binding, const LogicalType &element_type,
	                    bool &failed) {
		ExtractChainReducer reducer;
		ColumnBinding found;
		vector<string> field_path;
		LogicalType leaf_type;
		if (reducer.Reduce(expr, found, field_path, leaf_type) && found == element_binding) {
			if (field_path.size() != 1) {
				// the whole element, or a field nested deeper than the element struct: the
				// pre-nest filter is only defined over direct children of the element
				failed = true;
				return;
			}
			idx_t child_index;
			if (!FindStructChild(element_type, field_path[0], child_index)) {
				failed = true;
				return;
			}
			expr = make_uniq<BoundReferenceExpression>(field_path[0], leaf_type, child_index);
			return;
		}
		ExpressionIterator::EnumerateChildren(*expr, [&](unique_ptr<Expression> &child) {
			FlattenInPlace(child, element_binding, element_type, failed);
		});
	}

	//===------------------------------------------------------------------===//
	// source resolution - the root-relative dotted path of the unnested list
	//===------------------------------------------------------------------===//
	bool ResolveSource(LogicalUnnest &unnest, string &result) {
		auto &bound_unnest = unnest.expressions[0]->Cast<BoundUnnestExpression>();
		ExtractChainReducer reducer;
		ColumnBinding binding;
		vector<string> prefix;
		LogicalType leaf_type;
		if (!reducer.Reduce(bound_unnest.child, binding, prefix, leaf_type)) {
			return false;
		}
		vector<PrenestPathEntry> path;
		for (auto &name : prefix) {
			path.push_back(PrenestPathEntry {false, name});
		}
		for (idx_t guard = 0; guard < MAX_RESOLVE_DEPTH; guard++) {
			auto defining = FindDefiningOperator(binding.table_index);
			if (!defining) {
				return false;
			}
			auto &op = *defining;
			if (op.type == LogicalOperatorType::LOGICAL_GET) {
				auto &get = op.Cast<LogicalGet>();
				auto &column_ids = get.GetColumnIds();
				if (binding.column_index >= column_ids.size() || !column_ids[binding.column_index].HasPrimaryIndex()) {
					return false;
				}
				auto root_index = column_ids[binding.column_index].GetPrimaryIndex();
				if (root_index >= get.names.size()) {
					return false;
				}
				path.insert(path.begin(), PrenestPathEntry {false, get.names[root_index]});
				result = RenderPath(path);
				return true;
			}
			optional_ptr<unique_ptr<Expression>> source;
			auto through_unnest = false;
			if (op.type == LogicalOperatorType::LOGICAL_PROJECTION) {
				auto &proj = op.Cast<LogicalProjection>();
				if (binding.column_index >= proj.expressions.size()) {
					return false;
				}
				source = proj.expressions[binding.column_index];
			} else if (op.type == LogicalOperatorType::LOGICAL_UNNEST) {
				auto &other = op.Cast<LogicalUnnest>();
				if (binding.column_index >= other.expressions.size() ||
				    other.expressions[binding.column_index]->GetExpressionClass() != ExpressionClass::BOUND_UNNEST) {
					return false;
				}
				source = other.expressions[binding.column_index]->Cast<BoundUnnestExpression>().child;
				through_unnest = true;
			} else {
				return false;
			}
			ColumnBinding next;
			vector<string> names;
			LogicalType next_leaf;
			if (!reducer.Reduce(*source, next, names, next_leaf)) {
				return false;
			}
			vector<PrenestPathEntry> new_path;
			for (auto &name : names) {
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
		}
		return false;
	}

	optional_ptr<LogicalOperator> FindDefiningOperator(idx_t table_index) {
		auto entry = operators.find(table_index);
		if (entry == operators.end() || ambiguous.find(table_index) != ambiguous.end()) {
			return nullptr;
		}
		return entry->second;
	}

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
				operators.insert(make_pair(table_index.GetIndex(), optional_ptr<LogicalOperator>(op)));
			} else {
				ambiguous.insert(table_index.GetIndex());
			}
		}
		for (auto &child : op.children) {
			CollectOperators(*child);
		}
	}

	//===------------------------------------------------------------------===//
	// Pass 2 - a comprehension that reached the scan becomes a PrenestFilterSpec
	//===------------------------------------------------------------------===//
	void AbsorbAtScan(unique_ptr<LogicalOperator> &op) {
		for (auto &child : op->children) {
			AbsorbAtScan(child);
		}
		if (op->type != LogicalOperatorType::LOGICAL_FILTER || op->children.empty()) {
			return;
		}
		// walk through Projections to the scan; anything else (in particular another UNNEST)
		// means these comprehensions belong to a different list level
		auto cursor = op->children[0].get();
		while (cursor->type == LogicalOperatorType::LOGICAL_PROJECTION && !cursor->children.empty()) {
			cursor = cursor->children[0].get();
		}
		if (cursor->type != LogicalOperatorType::LOGICAL_GET) {
			return;
		}
		auto &get = cursor->Cast<LogicalGet>();
		if (!get.bind_data) {
			return;
		}

		// Decide first, move afterwards: nothing may be moved out of op->expressions until
		// the spec is known to be accepted, or an early return would leave null entries behind.
		// The reader supports one list per scan, so the first list that yields conditions wins.
		string list_source;
		vector<PrenestRawCondition> conditions;
		vector<bool> consumed(op->expressions.size(), false);
		for (idx_t i = 0; i < op->expressions.size(); i++) {
			auto &expr = op->expressions[i];
			if (expr->GetExpressionClass() != ExpressionClass::BOUND_COMPREHENSION) {
				continue;
			}
			auto &comprehension = expr->Cast<BoundComprehensionExpression>();
			if (!list_source.empty() && list_source != comprehension.source) {
				continue;
			}
			vector<PrenestRawCondition> extracted;
			if (!ToRawConditions(*comprehension.predicate, extracted) || extracted.empty()) {
				continue;
			}
			if (!SafeToTruncate(get, comprehension.source)) {
				stats.refused_list_read_elsewhere++;
				continue;
			}
			list_source = comprehension.source;
			consumed[i] = true;
			for (auto &condition : extracted) {
				conditions.push_back(std::move(condition));
			}
		}
		if (conditions.empty()) {
			return;
		}
		PrenestFilterSpec spec;
		spec.list_name = LastSegment(list_source);
		spec.conditions = std::move(conditions);
		if (!get.bind_data->TrySetPrenestFilter(spec)) {
			return;
		}
		stats.absorbed_at_scan++;
		// taking the consumed ones out keeps the roll-up from also claiming them, so the plan
		// reports where each comprehension actually ended up
		vector<unique_ptr<Expression>> kept;
		for (idx_t i = 0; i < op->expressions.size(); i++) {
			if (!consumed[i]) {
				kept.push_back(std::move(op->expressions[i]));
			}
		}
		op->expressions = std::move(kept);
		if (op->expressions.empty()) {
			op = std::move(op->children[0]);
		}
	}

	//! Convert the flattened predicate into the reader's conjunction form.
	bool ToRawConditions(const Expression &expr, vector<PrenestRawCondition> &result) {
		switch (expr.GetExpressionClass()) {
		case ExpressionClass::BOUND_CONJUNCTION: {
			auto &conj = expr.Cast<BoundConjunctionExpression>();
			if (conj.GetExpressionType() != ExpressionType::CONJUNCTION_AND) {
				return false;
			}
			for (auto &child : conj.children) {
				if (!ToRawConditions(*child, result)) {
					return false;
				}
			}
			return true;
		}
		case ExpressionClass::BOUND_COMPARISON: {
			auto &cmp = expr.Cast<BoundComparisonExpression>();
			auto type = cmp.GetExpressionType();
			if (!IsSupportedComparison(type)) {
				return false;
			}
			if (AddCondition(*cmp.left, *cmp.right, type, result)) {
				return true;
			}
			return AddCondition(*cmp.right, *cmp.left, FlipComparisonExpression(type), result);
		}
		case ExpressionClass::BOUND_BETWEEN: {
			// x BETWEEN a AND b is x >= a AND x <= b, and both halves reject a NULL x exactly
			// like BETWEEN does
			auto &between = expr.Cast<BoundBetweenExpression>();
			return AddCondition(*between.input, *between.lower, between.LowerComparisonType(), result) &&
			       AddCondition(*between.input, *between.upper, between.UpperComparisonType(), result);
		}
		default:
			return false;
		}
	}

	bool AddCondition(const Expression &field, const Expression &constant, ExpressionType comparison,
	                  vector<PrenestRawCondition> &result) {
		if (field.GetExpressionClass() != ExpressionClass::BOUND_REF ||
		    constant.GetExpressionClass() != ExpressionClass::BOUND_CONSTANT) {
			return false;
		}
		auto &value = constant.Cast<BoundConstantExpression>().value;
		if (value.IsNull()) {
			// comparing against NULL is never a plain ConstantFilter
			return false;
		}
		auto &ref = field.Cast<BoundReferenceExpression>();
		if (!IsSupportedLiteralType(ref.return_type) || value.type() != ref.return_type) {
			// a cast between the field and the comparison would mean the comparison happens at a
			// type other than the field's, while the reader casts the literal to the FIELD type
			return false;
		}
		PrenestRawCondition condition;
		condition.field = ref.GetName();
		condition.comparison = comparison;
		condition.literal = value.ToString();
		result.push_back(std::move(condition));
		return true;
	}

	//! Dropping elements changes the list itself, so anything reading the list outside the
	//! UNNEST chain would observe the truncation. `source` is rooted at one of the scan's
	//! columns: that column must be read exactly once - by the chain we followed - for the
	//! truncation to be invisible.
	//!
	//! This is narrower than gating on every intermediate binding: a sibling field of an
	//! enclosing element (o.o_orderpriority next to o.o_lineitems) is a different binding and
	//! does not block anything.
	bool SafeToTruncate(LogicalGet &get, const string &source) {
		auto root_name = source.substr(0, source.find('.'));
		auto &column_ids = get.GetColumnIds();
		for (idx_t i = 0; i < column_ids.size(); i++) {
			if (!column_ids[i].HasPrimaryIndex()) {
				continue;
			}
			auto index = column_ids[i].GetPrimaryIndex();
			if (index >= get.names.size() || !StringUtil::CIEquals(get.names[index], root_name)) {
				continue;
			}
			BindingUseCounter counter(ColumnBinding(get.table_index, i));
			counter.VisitOperator(*root);
			return counter.count == 1;
		}
		return false;
	}

	//===------------------------------------------------------------------===//
	// Pass 3 - roll the remaining comprehensions up into the nearest UNNEST above
	//===------------------------------------------------------------------===//
	void RollUp(unique_ptr<LogicalOperator> &op) {
		for (auto &child : op->children) {
			RollUp(child);
		}
		if (op->type != LogicalOperatorType::LOGICAL_UNNEST || op->children.empty()) {
			return;
		}
		auto &unnest = op->Cast<LogicalUnnest>();
		if (unnest.expressions.size() != 1) {
			return;
		}
		ExtractFrom(unnest, unnest.children[0]);
	}

	//! Walk down through Projections to the immediate Filter, stopping at anything else
	//! (another UNNEST or a scan) - the bottom-up order handles those separately.
	void ExtractFrom(LogicalUnnest &unnest, unique_ptr<LogicalOperator> &op) {
		if (op->type == LogicalOperatorType::LOGICAL_PROJECTION && !op->children.empty()) {
			ExtractFrom(unnest, op->children[0]);
			return;
		}
		if (op->type != LogicalOperatorType::LOGICAL_FILTER) {
			return;
		}
		vector<unique_ptr<Expression>> remaining;
		for (auto &expr : op->expressions) {
			if (expr->GetExpressionClass() != ExpressionClass::BOUND_COMPREHENSION) {
				remaining.push_back(std::move(expr));
				continue;
			}
			// the host UNNEST IS the binder for this level, so that layer is implicit: what
			// lands on `filters` is the bare per-element predicate
			auto &comprehension = expr->Cast<BoundComprehensionExpression>();
			unnest.filters.push_back(std::move(comprehension.predicate));
			stats.rolled_up++;
		}
		op->expressions = std::move(remaining);
		if (op->expressions.empty()) {
			op = std::move(op->children[0]);
		}
	}

	//===------------------------------------------------------------------===//
	// Pass 4 - nothing evaluates a comprehension, so none may survive
	//===------------------------------------------------------------------===//
	void StripLeftovers(unique_ptr<LogicalOperator> &op) {
		for (auto &child : op->children) {
			StripLeftovers(child);
		}
		if (op->type != LogicalOperatorType::LOGICAL_FILTER) {
			return;
		}
		vector<unique_ptr<Expression>> remaining;
		for (auto &expr : op->expressions) {
			if (expr->GetExpressionClass() == ExpressionClass::BOUND_COMPREHENSION) {
				stats.dropped++;
				continue;
			}
			remaining.push_back(std::move(expr));
		}
		op->expressions = std::move(remaining);
		if (op->expressions.empty() && !op->children.empty()) {
			op = std::move(op->children[0]);
		}
	}

private:
	static constexpr idx_t MAX_RESOLVE_DEPTH = 64;

	ClientContext &context;
	optional_ptr<LogicalOperator> root;
	unordered_map<idx_t, optional_ptr<LogicalOperator>> operators;
	unordered_set<idx_t> ambiguous;
	PrenestPushdownStats stats;
};

} // namespace

PrenestPushdownStats &PrenestPushdownStats::Get() {
	static PrenestPushdownStats stats;
	return stats;
}

void PrenestFilterPushdown::Optimize(unique_ptr<LogicalOperator> &plan) {
	Value enabled;
	if (!context.TryGetCurrentSetting("parquet_prenest_auto", enabled)) {
		// the setting only exists once the parquet extension is loaded
		return;
	}
	if (enabled.IsNull() || !BooleanValue::Get(enabled)) {
		return;
	}
	PrenestFilterExtractor extractor(context);
	PrenestPushdownStats::Get() = extractor.Run(plan);
}

} // namespace duckdb
