//===----------------------------------------------------------------------===//
//                         DuckDB
//
// reader/list_column_reader.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "column_reader.hpp"
#include "reader/templated_column_reader.hpp"

namespace duckdb {

class ListColumnReader : public ColumnReader {
public:
	static constexpr const PhysicalType TYPE = PhysicalType::LIST;

public:
	ListColumnReader(ParquetReader &reader, const ParquetColumnSchema &schema,
	                 unique_ptr<ColumnReader> child_column_reader_p);

	idx_t Read(uint64_t num_values, data_ptr_t define_out, data_ptr_t repeat_out, Vector &result_out) override;

	void ApplyPendingSkips(data_ptr_t define_out, data_ptr_t repeat_out) override;

	void InitializeRead(idx_t row_group_idx_p, const vector<ColumnChunk> &columns, TProtocol &protocol_p) override {
		child_column_reader->InitializeRead(row_group_idx_p, columns, protocol_p);
	}

	idx_t GroupRowsAvailable() override {
		return child_column_reader->GroupRowsAvailable() + overflow_child_count;
	}

	uint64_t TotalCompressedSize() override {
		return child_column_reader->TotalCompressedSize();
	}

	void RegisterPrefetch(ThriftFileTransport &transport, bool allow_merge) override {
		child_column_reader->RegisterPrefetch(transport, allow_merge);
	}

	//! [Rey hybrid / approach C] When enabled, this list reader collapses the ENTIRE nesting path below
	//! it into a single list per top-level row: values are grouped by repetition level 0 (rep>0 appends
	//! to the current top-level list, rep==0 starts a new one) instead of collapsing only at this list's
	//! own level (rep == MaxRepeat()). Combined with a child that reads a leaf column directly (skipping
	//! intermediate STRUCT/LIST assembly), this produces LIST<leaf> per top-level row so a single thin
	//! UNNEST can flatten it — avoiding the reconstruct+multi-UNNEST round-trip.
	//! NOTE (prototype): assumes no NULLs / empty lists at intermediate nesting levels; the def-level
	//! branch below still uses the leaf MaxDefine. Revisit for nullable/empty cases before general use.
	void SetCollapseToTopLevel(bool value) {
		collapse_to_top_level = value;
	}

protected:
	template <class OP>
	idx_t ReadInternal(uint64_t num_values, data_ptr_t define_out, data_ptr_t repeat_out,
	                   optional_ptr<Vector> result_out);

private:
	unique_ptr<ColumnReader> child_column_reader;
	ResizeableBuffer child_defines;
	ResizeableBuffer child_repeats;
	uint8_t *child_defines_ptr;
	uint8_t *child_repeats_ptr;

	VectorCache read_cache;
	Vector read_vector;

	idx_t overflow_child_count;

	//! [Rey hybrid / approach C] see SetCollapseToTopLevel above
	bool collapse_to_top_level = false;
};

} // namespace duckdb
