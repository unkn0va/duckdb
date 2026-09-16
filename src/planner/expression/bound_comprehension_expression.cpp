#include "duckdb/planner/expression/bound_comprehension_expression.hpp"

#include "duckdb/common/types/hash.hpp"

namespace duckdb {

BoundComprehensionExpression::BoundComprehensionExpression(string source_p, unique_ptr<Expression> predicate_p,
                                                           unique_ptr<Expression> inner_p)
    : Expression(ExpressionType::BOUND_COMPREHENSION, ExpressionClass::BOUND_COMPREHENSION, LogicalType::BOOLEAN),
      source(std::move(source_p)), predicate(std::move(predicate_p)), inner(std::move(inner_p)) {
}

const BoundComprehensionExpression &BoundComprehensionExpression::Innermost() const {
	reference<const BoundComprehensionExpression> current(*this);
	while (current.get().inner) {
		current = current.get().inner->Cast<BoundComprehensionExpression>();
	}
	return current.get();
}

string BoundComprehensionExpression::ToString() const {
	string body = predicate ? predicate->ToString() : "true";
	if (inner) {
		body = body + ", " + inner->ToString();
	}
	return "[x | x <- " + source + "; " + body + "]";
}

bool BoundComprehensionExpression::Equals(const BaseExpression &other_p) const {
	if (!Expression::Equals(other_p)) {
		return false;
	}
	auto &other = other_p.Cast<BoundComprehensionExpression>();
	if (source != other.source) {
		return false;
	}
	if (!Expression::Equals(predicate, other.predicate)) {
		return false;
	}
	return Expression::Equals(inner, other.inner);
}

hash_t BoundComprehensionExpression::Hash() const {
	auto result = Expression::Hash();
	result = CombineHash(result, duckdb::Hash(source.c_str(), source.size()));
	if (predicate) {
		result = CombineHash(result, predicate->Hash());
	}
	if (inner) {
		result = CombineHash(result, inner->Hash());
	}
	return result;
}

unique_ptr<Expression> BoundComprehensionExpression::Copy() const {
	auto copy = make_uniq<BoundComprehensionExpression>(source, predicate ? predicate->Copy() : nullptr,
	                                                   inner ? inner->Copy() : nullptr);
	copy->CopyProperties(*this);
	return std::move(copy);
}

} // namespace duckdb
