#include "reader/list_column_reader.hpp"
#include "parquet_reader.hpp"
#include "duckdb/common/types/selection_vector.hpp"

namespace duckdb {

struct ListReaderData {
	ListReaderData(list_entry_t *result_ptr, ValidityMask &result_mask)
	    : result_ptr(result_ptr), result_mask(result_mask) {
	}

	list_entry_t *result_ptr;
	ValidityMask &result_mask;
};

struct TemplatedListReader {
	using DATA = ListReaderData;

	static DATA Initialize(optional_ptr<Vector> result_out) {
		D_ASSERT(ListVector::GetListSize(*result_out) == 0);

		auto result_ptr = FlatVector::GetData<list_entry_t>(*result_out);
		auto &result_mask = FlatVector::Validity(*result_out);
		return ListReaderData(result_ptr, result_mask);
	}

	static idx_t GetOffset(optional_ptr<Vector> result_out) {
		return ListVector::GetListSize(*result_out);
	}

	static void HandleRepeat(DATA &data, idx_t offset) {
		data.result_ptr[offset].length++;
	}

	static void HandleListStart(DATA &data, idx_t offset, idx_t offset_in_child, idx_t length) {
		data.result_ptr[offset].offset = offset_in_child;
		data.result_ptr[offset].length = length;
	}

	static void HandleNull(DATA &data, idx_t offset) {
		data.result_mask.SetInvalid(offset);
		data.result_ptr[offset].offset = 0;
		data.result_ptr[offset].length = 0;
	}

	static void AppendVector(optional_ptr<Vector> result_out, Vector &read_vector, idx_t child_idx) {
		ListVector::Append(*result_out, read_vector, child_idx);
	}
};

struct TemplatedListSkipper {
	using DATA = bool;

	static DATA Initialize(optional_ptr<Vector>) {
		return false;
	}

	static idx_t GetOffset(optional_ptr<Vector>) {
		return 0;
	}

	static void HandleRepeat(DATA &, idx_t) {
	}

	static void HandleListStart(DATA &, idx_t, idx_t, idx_t) {
	}

	static void HandleNull(DATA &, idx_t) {
	}

	static void AppendVector(optional_ptr<Vector>, Vector &, idx_t) {
	}
};

template <class OP>
idx_t ListColumnReader::ReadInternal(uint64_t num_values, data_ptr_t define_out, data_ptr_t repeat_out,
                                     optional_ptr<Vector> result_out) {
	idx_t result_offset = 0;
	auto data = OP::Initialize(result_out);

	// if an individual list is longer than STANDARD_VECTOR_SIZE we actually have to loop the child read to fill it
	bool finished = false;
	while (!finished) {
		idx_t child_actual_num_values = 0;

		// check if we have any overflow from a previous read
		if (overflow_child_count == 0) {
			// we don't: read elements from the child reader
			child_defines.zero();
			child_repeats.zero();
			// we don't know in advance how many values to read because of the beautiful repetition/definition setup
			// we just read (up to) a vector from the child column, and see if we have read enough
			// if we have not read enough, we read another vector
			// if we have read enough, we leave any unhandled elements in the overflow vector for a subsequent read
			auto child_req_num_values =
			    MinValue<idx_t>(STANDARD_VECTOR_SIZE, child_column_reader->GroupRowsAvailable());
			read_vector.ResetFromCache(read_cache);
			child_actual_num_values =
			    child_column_reader->Read(child_req_num_values, child_defines_ptr, child_repeats_ptr, read_vector);
		} else {
			// we do: use the overflow values
			child_actual_num_values = overflow_child_count;
			overflow_child_count = 0;
		}

		if (child_actual_num_values == 0) {
			// no more elements available: we are done
			break;
		}
		read_vector.Verify(child_actual_num_values);
		idx_t current_chunk_offset = OP::GetOffset(result_out);

		// hard-won piece of code this, modify at your own risk
		// the intuition is that we have to only collapse values into lists that are repeated *on this level*
		// the rest is pretty much handed up as-is as a single-valued list or NULL
		idx_t child_idx;
		for (child_idx = 0; child_idx < child_actual_num_values; child_idx++) {
			if (child_repeats_ptr[child_idx] == MaxRepeat()) {
				// value repeats on this level, append
				D_ASSERT(result_offset > 0);
				OP::HandleRepeat(data, result_offset - 1);
				continue;
			}

			if (result_offset >= num_values) {
				// we ran out of output space
				finished = true;
				break;
			}
			if (child_defines_ptr[child_idx] >= MaxDefine()) {
				// value has been defined down the stack, hence its NOT NULL
				OP::HandleListStart(data, result_offset, child_idx + current_chunk_offset, 1);
			} else if (child_defines_ptr[child_idx] == MaxDefine() - 1) {
				// empty list
				OP::HandleListStart(data, result_offset, child_idx + current_chunk_offset, 0);
			} else {
				// value is NULL somewhere up the stack
				OP::HandleNull(data, result_offset);
			}

			if (repeat_out) {
				repeat_out[result_offset] = child_repeats_ptr[child_idx];
			}
			if (define_out) {
				define_out[result_offset] = child_defines_ptr[child_idx];
			}

			result_offset++;
		}
		// actually append the required elements to the child list
		OP::AppendVector(result_out, read_vector, child_idx);

		// we have read more values from the child reader than we can fit into the result for this read
		// we have to pass everything from child_idx to child_actual_num_values into the next call
		if (child_idx < child_actual_num_values && result_offset == num_values) {
			read_vector.Slice(read_vector, child_idx, child_actual_num_values);
			overflow_child_count = child_actual_num_values - child_idx;
			read_vector.Verify(overflow_child_count);

			// move values in the child repeats and defines *backward* by child_idx
			for (idx_t repdef_idx = 0; repdef_idx < overflow_child_count; repdef_idx++) {
				child_defines_ptr[repdef_idx] = child_defines_ptr[child_idx + repdef_idx];
				child_repeats_ptr[repdef_idx] = child_repeats_ptr[child_idx + repdef_idx];
			}
		}
	}
	return result_offset;
}


//===--------------------------------------------------------------------===//
// PROBE: filtered list assembly
//===--------------------------------------------------------------------===//
// Mirrors ReadInternal<TemplatedListReader>, except that only elements passing
// the predicate are appended to the child vector. The stock loop writes a list's
// offset as `child_idx + current_chunk_offset`, which presumes the whole prefix
// [0, child_idx) is appended 1:1 and gap-free. Here the offset comes from a
// running survivor count instead, and the append goes through a selection
// vector. Everything else - the record-boundary logic, the def-level cases and
// the carry-over at the end - is unchanged.
idx_t ListColumnReader::ReadFilteredInternal(uint64_t num_values, data_ptr_t define_out, data_ptr_t repeat_out,
                                             Vector &result_out) {
	D_ASSERT(prenest_filter);
	D_ASSERT(ListVector::GetListSize(result_out) == 0);

	auto &stats = PrenestStats::Get();
	auto result_ptr = FlatVector::GetData<list_entry_t>(result_out);
	auto &result_mask = FlatVector::Validity(result_out);
	auto keep = prenest_keep.get();

	idx_t result_offset = 0;
	bool finished = false;
	while (!finished) {
		idx_t child_actual_num_values = 0;

		if (overflow_child_count == 0) {
			child_defines.zero();
			child_repeats.zero();
			auto child_req_num_values =
			    MinValue<idx_t>(STANDARD_VECTOR_SIZE, child_column_reader->GroupRowsAvailable());
			read_vector.ResetFromCache(read_cache);
			child_actual_num_values =
			    child_column_reader->Read(child_req_num_values, child_defines_ptr, child_repeats_ptr, read_vector);
			// counted here only, so carried-over values are not double counted
			stats.elements_decoded += child_actual_num_values;
		} else {
			child_actual_num_values = overflow_child_count;
			overflow_child_count = 0;
		}

		if (child_actual_num_values == 0) {
			break;
		}
		read_vector.Verify(child_actual_num_values);

		// the carry-over path below leaves read_vector as a DICTIONARY vector.
		// StructVector::GetEntries looks straight past a dictionary's selection
		// (vector.cpp:2558), so the predicate needs resolved values here.
		if (read_vector.GetVectorType() != VectorType::FLAT_VECTOR) {
			read_vector.Flatten(child_actual_num_values);
			stats.carryover_flattens++;
		}

		SelectionVector filter_sel(prenest_sel_data.get());
		SelectionVector append_sel(prenest_append_sel_data.get());
		prenest_filter->Apply(read_vector, child_actual_num_values, filter_sel, keep);
		stats.inner_iterations++;

		idx_t current_chunk_offset = ListVector::GetListSize(result_out);
		idx_t kept = 0;

		idx_t child_idx;
		for (child_idx = 0; child_idx < child_actual_num_values; child_idx++) {
			if (child_repeats_ptr[child_idx] == MaxRepeat()) {
				// continues the list opened by the previous output row
				D_ASSERT(result_offset > 0);
				if (keep[child_idx]) {
					result_ptr[result_offset - 1].length++;
					append_sel.set_index(kept++, child_idx);
				}
				continue;
			}

			if (result_offset >= num_values) {
				// we ran out of output space
				finished = true;
				break;
			}
			if (child_defines_ptr[child_idx] >= MaxDefine()) {
				// a present element - opens a new list, whether or not it survives.
				// a row all of whose elements are dropped therefore becomes EMPTY,
				// not NULL and not absent.
				result_ptr[result_offset].offset = current_chunk_offset + kept;
				if (keep[child_idx]) {
					result_ptr[result_offset].length = 1;
					append_sel.set_index(kept++, child_idx);
				} else {
					result_ptr[result_offset].length = 0;
				}
			} else if (child_defines_ptr[child_idx] == MaxDefine() - 1) {
				// empty list - the placeholder value is never appended
				result_ptr[result_offset].offset = current_chunk_offset + kept;
				result_ptr[result_offset].length = 0;
			} else {
				// NULL somewhere up the stack
				result_mask.SetInvalid(result_offset);
				result_ptr[result_offset].offset = 0;
				result_ptr[result_offset].length = 0;
			}

			if (repeat_out) {
				repeat_out[result_offset] = child_repeats_ptr[child_idx];
			}
			if (define_out) {
				define_out[result_offset] = child_defines_ptr[child_idx];
			}

			result_offset++;
		}

		if (kept > 0) {
			ListVector::Append(result_out, read_vector, append_sel, kept, 0);
			stats.elements_appended += kept;
		}

		if (child_idx < child_actual_num_values && result_offset == num_values) {
			stats.carryovers++;
			read_vector.Slice(read_vector, child_idx, child_actual_num_values);
			overflow_child_count = child_actual_num_values - child_idx;
			read_vector.Verify(overflow_child_count);

			for (idx_t repdef_idx = 0; repdef_idx < overflow_child_count; repdef_idx++) {
				child_defines_ptr[repdef_idx] = child_defines_ptr[child_idx + repdef_idx];
				child_repeats_ptr[repdef_idx] = child_repeats_ptr[child_idx + repdef_idx];
			}
		}
	}
	return result_offset;
}

void ListColumnReader::SetPrenestFilter(unique_ptr<PrenestFilter> filter) {
	prenest_filter = std::move(filter);
	if (prenest_filter && !prenest_keep) {
		prenest_keep = make_unsafe_uniq_array<bool>(STANDARD_VECTOR_SIZE);
		prenest_sel_data = make_unsafe_uniq_array<sel_t>(STANDARD_VECTOR_SIZE);
		prenest_append_sel_data = make_unsafe_uniq_array<sel_t>(STANDARD_VECTOR_SIZE);
	}
}

idx_t ListColumnReader::Read(uint64_t num_values, data_ptr_t define_out, data_ptr_t repeat_out, Vector &result_out) {
	ApplyPendingSkips(define_out, repeat_out);
	if (prenest_filter) {
		return ReadFilteredInternal(num_values, define_out, repeat_out, result_out);
	}
	return ReadInternal<TemplatedListReader>(num_values, define_out, repeat_out, result_out);
}

ListColumnReader::ListColumnReader(ParquetReader &reader, const ParquetColumnSchema &schema,
                                   unique_ptr<ColumnReader> child_column_reader_p)
    : ColumnReader(reader, schema), child_column_reader(std::move(child_column_reader_p)),
      read_cache(reader.allocator, ListType::GetChildType(Type())), read_vector(read_cache), overflow_child_count(0) {
	child_defines.resize(reader.allocator, STANDARD_VECTOR_SIZE);
	child_repeats.resize(reader.allocator, STANDARD_VECTOR_SIZE);
	child_defines_ptr = (uint8_t *)child_defines.ptr;
	child_repeats_ptr = (uint8_t *)child_repeats.ptr;
}

void ListColumnReader::ApplyPendingSkips(data_ptr_t define_out, data_ptr_t repeat_out) {
	ReadInternal<TemplatedListSkipper>(pending_skips, nullptr, nullptr, nullptr);
	pending_skips = 0;
}

} // namespace duckdb
