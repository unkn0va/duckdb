#include "duckdb/execution/operator/projection/physical_unnest.hpp"

#include "duckdb/common/uhugeint.hpp"
#include "duckdb/common/vector_operations/vector_operations.hpp"
#include "duckdb/common/algorithm.hpp"
#include "duckdb/execution/expression_executor.hpp"
#include "duckdb/planner/expression/bound_reference_expression.hpp"
#include "duckdb/planner/expression/bound_unnest_expression.hpp"

namespace duckdb {

class UnnestOperatorState : public OperatorState {
public:
	UnnestOperatorState(ClientContext &context, const vector<unique_ptr<Expression>> &select_list,
	                    const vector<unique_ptr<Expression>> *element_filters)
	    : current_row(0), list_position(0), first_fetch(true), input_sel(STANDARD_VECTOR_SIZE), executor(context),
	      filter_sel(STANDARD_VECTOR_SIZE) {
		// for each UNNEST in the select_list, we add the child expression to the expression executor
		// and set the return type in the list_data chunk, which will contain the evaluated expression results
		vector<LogicalType> list_data_types;
		for (auto &exp : select_list) {
			D_ASSERT(exp->GetExpressionType() == ExpressionType::BOUND_UNNEST);
			auto &bue = exp->Cast<BoundUnnestExpression>();
			list_data_types.push_back(bue.child->return_type);
			executor.AddExpression(*bue.child.get());

			unnest_sels.emplace_back(STANDARD_VECTOR_SIZE);
			null_sels.emplace_back(STANDARD_VECTOR_SIZE);
		}
		null_counts.resize(list_data_types.size());

		auto &allocator = Allocator::Get(context);
		list_data.Initialize(allocator, list_data_types);

		list_vector_data.resize(list_data.ColumnCount());
		list_child_data.resize(list_data.ColumnCount());

		if (element_filters && !element_filters->empty()) {
			// The absorbed filters are evaluated against the elements of the single unnested list.
			// PushdownUnnest only absorbs filters when this shape holds, so anything else is a bug:
			// silently ignoring the filters would return too many rows.
			if (select_list.size() != 1) {
				throw InternalException("UNNEST element filters require exactly one UNNEST expression");
			}
			auto &child_type = select_list[0]->Cast<BoundUnnestExpression>().child->return_type;
			if (child_type.id() != LogicalTypeId::LIST) {
				throw InternalException("UNNEST element filters require a LIST child, found %s",
				                        child_type.ToString());
			}
			vector<LogicalType> element_types {ListType::GetChildType(child_type)};
			element_chunk.InitializeEmpty(element_types);
			for (auto &filter : *element_filters) {
				auto filter_executor = make_uniq<ExpressionExecutor>(context);
				filter_executor->AddExpression(*filter);
				filter_executors.push_back(std::move(filter_executor));
			}
		}
	}

	idx_t current_row;
	idx_t list_position;
	unsafe_vector<idx_t> unnest_lengths;
	bool first_fetch;
	SelectionVector input_sel;
	vector<SelectionVector> unnest_sels;
	vector<SelectionVector> null_sels;
	vector<idx_t> null_counts;

	ExpressionExecutor executor;
	DataChunk list_data;
	vector<UnifiedVectorFormat> list_vector_data;
	vector<UnifiedVectorFormat> list_child_data;

	//! ---- absorbed element filters (see PhysicalUnnest::element_filters) ----
	//! One executor per absorbed conjunct. Empty when there is nothing to prefilter, which is
	//! also how the loop below decides between the filtered and the regular path.
	vector<unique_ptr<ExpressionExecutor>> filter_executors;
	//! Single-column chunk that references a window of the list's child vector.
	DataChunk element_chunk;
	//! Scratch selection vector for chaining the conjuncts.
	SelectionVector filter_sel;
	//! Per-element survival flag, indexed by child-vector index.
	unsafe_vector<uint8_t> survives;
	//! Child-vector indices of the surviving elements, grouped by input row.
	unsafe_vector<idx_t> survivor_indices;
	//! Input row r owns survivor_indices[survivor_offsets[r] .. survivor_offsets[r + 1]).
	unsafe_vector<idx_t> survivor_offsets;
	//! Whether the filter actually removed anything from the current input chunk. When it did not,
	//! the survivor arrays are not built at all and the regular path runs instead - materialising
	//! one index per element is only worth it if it saves output rows.
	bool filter_prunes_chunk = false;

	bool HasElementFilter() const {
		return !filter_executors.empty();
	}

public:
	//! Reset the fields of the unnest operator state
	void Reset();
	//! Prepare the input for the next unnest
	void PrepareInput(DataChunk &input, const vector<unique_ptr<Expression>> &select_list);

private:
	//! Evaluate the absorbed filters over the list's elements and rewrite unnest_lengths so the
	//! main loop only ever emits surviving elements.
	void ApplyElementFilter();
};

void UnnestOperatorState::Reset() {
	current_row = 0;
	list_position = 0;
	first_fetch = true;
}

PhysicalUnnest::PhysicalUnnest(PhysicalPlan &physical_plan, vector<LogicalType> types,
                               vector<unique_ptr<Expression>> select_list,
                               vector<unique_ptr<Expression>> element_filters, idx_t estimated_cardinality,
                               PhysicalOperatorType type)
    : PhysicalOperator(physical_plan, type, std::move(types), estimated_cardinality),
      select_list(std::move(select_list)), element_filters(std::move(element_filters)) {
	D_ASSERT(!this->select_list.empty());
}

InsertionOrderPreservingMap<string> PhysicalUnnest::ParamsToString() const {
	InsertionOrderPreservingMap<string> result;
	if (!element_filters.empty()) {
		string filters_info;
		for (idx_t i = 0; i < element_filters.size(); i++) {
			if (i > 0) {
				filters_info += "\n";
			}
			filters_info += element_filters[i]->GetName();
		}
		result["Element Filters"] = filters_info;
	}
	SetEstimatedCardinality(result, estimated_cardinality);
	return result;
}

void UnnestOperatorState::PrepareInput(DataChunk &input, const vector<unique_ptr<Expression>> &select_list) {
	list_data.Reset();
	// execute the expressions inside each UNNEST in the select_list to get the list data
	// execution results (lists) are kept in list_data chunk
	executor.Execute(input, list_data);

	// verify incoming lists
	list_data.Verify(executor.HasContext() ? executor.GetContext().db : nullptr);
	D_ASSERT(input.size() == list_data.size());
	D_ASSERT(list_data.ColumnCount() == select_list.size());
	D_ASSERT(list_vector_data.size() == list_data.ColumnCount());
	D_ASSERT(list_child_data.size() == list_data.ColumnCount());

	// get the UnifiedVectorFormat of each list_data vector (LIST vectors for the different UNNESTs)
	// both for the vector itself and its child vector
	for (idx_t col_idx = 0; col_idx < list_data.ColumnCount(); col_idx++) {
		auto &list_vector = list_data.data[col_idx];
		list_vector.ToUnifiedFormat(list_data.size(), list_vector_data[col_idx]);

		if (list_vector.GetType() == LogicalType::SQLNULL) {
			// UNNEST(NULL): SQLNULL vectors don't have child vectors, but we need to point to the child vector of
			// each vector, so we just get the UnifiedVectorFormat of the vector itself
			auto &child_vector = list_vector;
			child_vector.ToUnifiedFormat(0, list_child_data[col_idx]);
		} else {
			auto list_size = ListVector::GetListSize(list_vector);
			auto &child_vector = ListVector::GetEntry(list_vector);
			child_vector.ToUnifiedFormat(list_size, list_child_data[col_idx]);
		}
	}
	// get the unnest lengths
	if (list_data.size() > unnest_lengths.size()) {
		unnest_lengths.resize(list_data.size());
	}
	for (idx_t r = 0; r < list_data.size(); r++) {
		unnest_lengths[r] = 0;
	}
	for (idx_t col_idx = 0; col_idx < list_data.ColumnCount(); col_idx++) {
		auto &vector_data = list_vector_data[col_idx];
		for (idx_t r = 0; r < list_data.size(); r++) {
			auto current_idx = vector_data.sel->get_index(r);
			if (!vector_data.validity.RowIsValid(current_idx)) {
				continue;
			}
			// check if this list is longer than the current unnest length
			auto list_data_entries = UnifiedVectorFormat::GetData<list_entry_t>(vector_data);
			auto list_entry = list_data_entries[current_idx];
			if (list_entry.length > unnest_lengths[r]) {
				unnest_lengths[r] = list_entry.length;
			}
		}
	}

	if (HasElementFilter()) {
		ApplyElementFilter();
	}

	first_fetch = false;
}

void UnnestOperatorState::ApplyElementFilter() {
	// Guaranteed by the constructor: a single UNNEST over a LIST.
	D_ASSERT(list_data.ColumnCount() == 1);
	auto &list_vector = list_data.data[0];
	const auto count = list_data.size();
	const auto list_size = ListVector::GetListSize(list_vector);

	filter_prunes_chunk = false;
	if (list_size == 0) {
		// no elements to prefilter - the regular path already emits nothing for NULL/empty lists
		return;
	}

	// Evaluate the predicates once over the whole child vector. The child vector holds the
	// elements of every list in this chunk back to back, so it can be longer than a single
	// vector - walk it in STANDARD_VECTOR_SIZE windows.
	survives.resize(list_size);
	std::fill_n(survives.data(), list_size, 0);
	idx_t matched_total = 0;
	auto &child_vector = ListVector::GetEntry(list_vector);
	for (idx_t base = 0; base < list_size; base += STANDARD_VECTOR_SIZE) {
		const auto window = MinValue<idx_t>(STANDARD_VECTOR_SIZE, list_size - base);
		element_chunk.data[0].Slice(child_vector, base, base + window);
		element_chunk.SetCardinality(window);

		// Chain the conjuncts: each round only re-evaluates the elements that are still alive,
		// which is the same scheme ExpressionExecutor uses for a CONJUNCTION_AND.
		optional_ptr<SelectionVector> current_sel;
		auto current_count = window;
		for (auto &filter_executor : filter_executors) {
			current_count =
			    filter_executor->SelectExpression(element_chunk, &filter_sel, nullptr, current_sel, current_count);
			if (current_count == 0) {
				break;
			}
			current_sel = &filter_sel;
		}
		matched_total += current_count;
		if (current_count == window) {
			// nothing was filtered out of this window
			std::fill_n(survives.data() + base, window, 1);
		} else {
			for (idx_t i = 0; i < current_count; i++) {
				survives[base + filter_sel.get_index(i)] = 1;
			}
		}
	}

	if (matched_total == list_size) {
		// Every element passes, so there is nothing to skip. Leave unnest_lengths alone and let the
		// regular path run: building a survivor index per element would be pure overhead here.
		// We still saved the Filter operator above the UNNEST, which is where this predicate used
		// to be evaluated.
		return;
	}

	// Group the survivors by input row and make unnest_lengths count survivors instead of list
	// entries. From here on the main loop is unchanged: it still walks unnest_lengths[row] output
	// slots per row, there are just fewer of them.
	survivor_offsets.resize(count + 1);
	survivor_indices.clear();
	if (survivor_indices.capacity() < matched_total) {
		survivor_indices.reserve(matched_total);
	}
	auto &vector_data = list_vector_data[0];
	auto entries = UnifiedVectorFormat::GetData<list_entry_t>(vector_data);
	for (idx_t r = 0; r < count; r++) {
		survivor_offsets[r] = survivor_indices.size();
		const auto current_idx = vector_data.sel->get_index(r);
		if (vector_data.validity.RowIsValid(current_idx)) {
			const auto entry = entries[current_idx];
			for (idx_t k = 0; k < entry.length; k++) {
				const auto child_idx = entry.offset + k;
				// list entries always index into ListVector::GetEntry, which is the vector we sized
				// `survives` after - the same invariant the regular path relies on for unnest_sels
				D_ASSERT(child_idx < list_size);
				if (survives[child_idx]) {
					survivor_indices.push_back(child_idx);
				}
			}
		}
		unnest_lengths[r] = survivor_indices.size() - survivor_offsets[r];
	}
	survivor_offsets[count] = survivor_indices.size();
	filter_prunes_chunk = true;
}

unique_ptr<OperatorState> PhysicalUnnest::GetOperatorState(ExecutionContext &context) const {
	return PhysicalUnnest::GetState(context, select_list, &element_filters);
}

unique_ptr<OperatorState> PhysicalUnnest::GetState(ExecutionContext &context,
                                                   const vector<unique_ptr<Expression>> &select_list,
                                                   const vector<unique_ptr<Expression>> *element_filters) {
	return make_uniq<UnnestOperatorState>(context.client, select_list, element_filters);
}

OperatorResultType PhysicalUnnest::ExecuteInternal(ExecutionContext &context, DataChunk &input, DataChunk &chunk,
                                                   OperatorState &state_p,
                                                   const vector<unique_ptr<Expression>> &select_list,
                                                   bool include_input) {
	auto &state = state_p.Cast<UnnestOperatorState>();

	do {
		// prepare the input data by executing any expressions and getting the
		// UnifiedVectorFormat of each LIST vector (list_vector_data) and its child vector (list_child_data)
		if (state.first_fetch) {
			state.PrepareInput(input, select_list);
		}

		// finished with all rows of this input chunk, reset
		if (state.current_row >= input.size()) {
			state.Reset();
			return OperatorResultType::NEED_MORE_INPUT;
		}

		// we essentially create two different SelectionVectors to slice
		// one is for the input (if include_input is set)
		// the other is for the list we are unnesting
		// construct these
		idx_t result_length = 0;
		idx_t unnest_list_count = 0;
		auto initial_row = state.current_row;
		for (idx_t col_idx = 0; col_idx < state.list_data.ColumnCount(); col_idx++) {
			state.null_counts[col_idx] = 0;
		}
		while (result_length < STANDARD_VECTOR_SIZE && state.current_row < input.size()) {
			auto current_row_length = MinValue<idx_t>(STANDARD_VECTOR_SIZE - result_length,
			                                          state.unnest_lengths[state.current_row] - state.list_position);

			if (current_row_length > 0) {
				// set up the selection vectors
				if (include_input) {
					for (idx_t r = 0; r < current_row_length; r++) {
						state.input_sel.set_index(result_length + r, state.current_row);
					}
				}
				for (idx_t col_idx = 0; col_idx < state.list_data.ColumnCount(); col_idx++) {
					if (state.filter_prunes_chunk) {
						// This is the whole point of absorbing the filter: the surviving child indices
						// were grouped per input row up front and unnest_lengths counts exactly those
						// survivors, so every output slot we create here maps to an element that passes
						// the predicate. Elements that do not are never given a slot, hence never copied,
						// and no Filter operator has to revisit them. There is also nothing to NULL-pad:
						// that only happens when several lists of different lengths are unnested at once,
						// which the absorbed-filter shape rules out.
						const auto base = state.survivor_offsets[state.current_row] + state.list_position;
						for (idx_t r = 0; r < current_row_length; r++) {
							state.unnest_sels[col_idx].set_index(result_length + r,
							                                     state.survivor_indices[base + r]);
						}
						continue;
					}
					auto &vector_data = state.list_vector_data[col_idx];
					auto current_idx = vector_data.sel->get_index(state.current_row);
					idx_t list_length = 0;
					idx_t list_offset = 0;
					if (vector_data.validity.RowIsValid(current_idx)) {
						auto list_data = UnifiedVectorFormat::GetData<list_entry_t>(vector_data);
						auto list_entry = list_data[current_idx];
						list_length = list_entry.length;
						list_offset = list_entry.offset;
					}
					// unnest any entries we can
					idx_t unnest_length = MinValue<idx_t>(
					    list_length - MinValue<idx_t>(list_length, state.list_position), current_row_length);
					auto &unnest_sel = state.unnest_sels[col_idx];
					for (idx_t r = 0; r < unnest_length; r++) {
						unnest_sel.set_index(result_length + r, list_offset + state.list_position + r);
					}
					// for any remaining entries (if any) - set them in the null selection
					auto &null_sel = state.null_sels[col_idx];
					for (idx_t r = unnest_length; r < current_row_length; r++) {
						// we unnest the first row in the child list
						// this is chosen arbitrarily - we will override it with `NULL` afterwards
						// FIXME if the child list has a `NULL` entry we can directly unnest that and avoid having
						// to override it - this is a potential optimization we could do in the future
						unnest_sel.set_index(result_length + r, 0);
						null_sel.set_index(state.null_counts[col_idx]++, result_length + r);
					}
				}

				// move to the next row
				result_length += current_row_length;
				state.list_position += current_row_length;
			}
			unnest_list_count++;
			if (state.list_position == state.unnest_lengths[state.current_row]) {
				state.current_row++;
				state.list_position = 0;
			}
		}
		idx_t col_offset = 0;
		chunk.SetCardinality(result_length);
		if (include_input) {
			for (idx_t col_idx = 0; col_idx < input.ColumnCount(); col_idx++) {
				if (unnest_list_count == 1) {
					// everything belongs to the same row - we can do a constant reference
					ConstantVector::Reference(chunk.data[col_idx], input.data[col_idx], initial_row, input.size());
				} else {
					// input values come from different rows - we need to slice
					chunk.data[col_idx].Slice(input.data[col_idx], state.input_sel, result_length);
				}
			}
			col_offset = input.ColumnCount();
		}
		for (idx_t col_idx = 0; col_idx < state.list_data.ColumnCount(); col_idx++) {
			auto &list_vector = state.list_data.data[col_idx];
			auto &result_vector = chunk.data[col_offset + col_idx];
			if (state.list_data.data[col_idx].GetType() == LogicalType::SQLNULL ||
			    ListType::GetChildType(state.list_data.data[col_idx].GetType()) == LogicalType::SQLNULL ||
			    ListVector::GetListSize(list_vector) == 0) {
				// UNNEST(NULL) or UNNEST([])
				// we cannot slice empty lists - but if our child list is empty we can only return NULL anyway
				result_vector.SetVectorType(VectorType::CONSTANT_VECTOR);
				ConstantVector::SetNull(result_vector, true);
				continue;
			}
			auto &child_vector = ListVector::GetEntry(list_vector);
			result_vector.Slice(child_vector, state.unnest_sels[col_idx], result_length);
			if (state.null_counts[col_idx] > 0) {
				// we have NULL values that we need to set - flatten
				result_vector.Flatten(result_length);
				auto &null_sel = state.null_sels[col_idx];
				for (idx_t idx = 0; idx < state.null_counts[col_idx]; idx++) {
					auto null_index = null_sel.get_index(idx);
					FlatVector::SetNull(result_vector, null_index, true);
				}
			}
		}
	} while (chunk.size() == 0);
	return OperatorResultType::HAVE_MORE_OUTPUT;
}

OperatorResultType PhysicalUnnest::Execute(ExecutionContext &context, DataChunk &input, DataChunk &chunk,
                                           GlobalOperatorState &, OperatorState &state) const {
	return ExecuteInternal(context, input, chunk, state, select_list);
}

} // namespace duckdb
