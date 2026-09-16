#include "duckdb/planner/expression/bound_comprehension_expression.hpp"

#include "duckdb/common/types/hash.hpp"

namespace duckdb {

BoundComprehensionExpression::BoundComprehensionExpression(string source_p, unique_ptr<Expression> predicate_p)
    : Expression(ExpressionType::BOUND_COMPREHENSION, ExpressionClass::BOUND_COMPREHENSION, LogicalType::BOOLEAN),
      source(std::move(source_p)), predicate(std::move(predicate_p)) {
}

string BoundComprehensionExpression::ToString() const {
	return "[x | x <- " + source + "; " + (predicate ? predicate->ToString() : "true") + "]";
}

bool BoundComprehensionExpression::Equals(const BaseExpression &other_p) const {
	if (!Expression::Equals(other_p)) {
		return false;
	}
	auto &other = other_p.Cast<BoundComprehensionExpression>();
	if (source != other.source) {
		return false;
	}
	return Expression::Equals(predicate, other.predicate);
}

hash_t BoundComprehensionExpression::Hash() const {
	auto result = Expression::Hash();
	result = CombineHash(result, duckdb::Hash(source.c_str(), source.size()));
	if (predicate) {
		result = CombineHash(result, predicate->Hash());
	}
	return result;
}

unique_ptr<Expression> BoundComprehensionExpression::Copy() const {
	auto copy = make_uniq<BoundComprehensionExpression>(source, predicate ? predicate->Copy() : nullptr);
	copy->CopyProperties(*this);
	return std::move(copy);
}

} // namespace duckdb
