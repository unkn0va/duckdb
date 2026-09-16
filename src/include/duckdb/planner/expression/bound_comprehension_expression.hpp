//===----------------------------------------------------------------------===//
//                         DuckDB
//
// duckdb/planner/expression/bound_comprehension_expression.hpp
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/planner/expression.hpp"

namespace duckdb {

//! A nested filter expressed as a list comprehension:
//!
//!   [ol | ol <- c_orders.o_lineitems; ol.l_partkey < 100]
//!
//! `source` is the full root-relative path of the list this level iterates
//! ("c_orders.o_lineitems"), and `predicate` is that level's predicate in FLAT
//! form: its leaves reference the element struct's fields directly
//! (BoundReferenceExpression, indexed by struct child position) rather than
//! through a chain of struct_extract calls. That is what lets the predicate be
//! evaluated against the element struct's columns with no extract indirection.
//!
//! This is a marker expression carried by the optimizer, NOT something the
//! execution engine ever evaluates. It is created by PrenestFilterPushdown,
//! absorbed either into a scan's PrenestFilterSpec or into LogicalUnnest::filters,
//! and any that survive are stripped before the rule returns.
class BoundComprehensionExpression : public Expression {
public:
	static constexpr const ExpressionClass TYPE = ExpressionClass::BOUND_COMPREHENSION;

public:
	BoundComprehensionExpression(string source, unique_ptr<Expression> predicate);

	//! Root-relative dotted path of the list whose elements are iterated
	string source;
	//! Per-element predicate, flattened against the element struct
	unique_ptr<Expression> predicate;

public:
	string ToString() const override;

	bool Equals(const BaseExpression &other) const override;
	hash_t Hash() const override;

	unique_ptr<Expression> Copy() const override;

	void Serialize(Serializer &serializer) const override;
	static unique_ptr<Expression> Deserialize(Deserializer &deserializer);
};

} // namespace duckdb
