//===----------------------------------------------------------------------===//
//                         DuckDB
//
// reader/list_column_reader.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "column_reader.hpp"
#include "prenest_filter.hpp"
#include "reader/templated_column_reader.hpp"

namespace duckdb {

class ListColumnReader : public ColumnReader {
public:
	static constexpr const PhysicalType TYPE = PhysicalType::LIST;

public:
	ListColumnReader(const ParquetReader &reader, const ParquetColumnSchema &schema,
	                 unique_ptr<ColumnReader> child_column_reader_p);
	ColumnReader &GetChildReader();

	idx_t Read(ColumnReaderInput &input, Vector &result) override;

	void ApplyPendingSkips(data_ptr_t define_out, data_ptr_t repeat_out) override;

	void InitializeRead(idx_t row_group_idx_p, idx_t row_group_num_rows, const vector<ColumnChunk> &columns,
	                    TProtocol &protocol_p) override {
		child_column_reader->InitializeRead(row_group_idx_p, row_group_num_rows, columns, protocol_p);
	}

	idx_t GroupRowsAvailable() override {
		return child_column_reader->GroupRowsAvailable() + overflow_child_count;
	}

	void GatherColumnChunks(unordered_set<idx_t> &column_chunks) override {
		child_column_reader->GatherColumnChunks(column_chunks);
	}

	void RegisterPrefetch(ThriftFileTransport &transport, bool allow_merge) override {
		child_column_reader->RegisterPrefetch(transport, allow_merge);
	}

	//! PROBE: attach an element-level predicate applied during list assembly.
	//! When unset, Read() runs the unmodified stock path.
	void SetPrenestFilter(unique_ptr<PrenestFilter> filter);

protected:
	template <class OP>
	idx_t ReadInternal(ColumnReaderInput &input, optional_ptr<Vector> result_out);
	//! PROBE: single-pass filtered assembly. Deliberately a separate method so the
	//! stock loop above is byte-identical when no filter is attached.
	idx_t ReadFilteredInternal(ColumnReaderInput &input, Vector &result_out);

private:
	unique_ptr<ColumnReader> child_column_reader;
	ResizeableBuffer child_defines;
	ResizeableBuffer child_repeats;
	uint8_t *child_defines_ptr;
	uint8_t *child_repeats_ptr;

	VectorCache read_cache;
	Vector read_vector;

	idx_t overflow_child_count;

	//! PROBE state
	unique_ptr<PrenestFilter> prenest_filter;
	unsafe_unique_array<bool> prenest_keep;
	//! Backing storage for the two selection vectors. ColumnSegment::FilterSelection
	//! may re-Initialize the SelectionVector it is handed (e.g. the CONJUNCTION_OR
	//! path rebinds it to a freshly sized buffer), so a SelectionVector member
	//! would silently shrink between iterations. Non-owning views over these
	//! arrays are constructed per iteration instead.
	unsafe_unique_array<sel_t> prenest_sel_data;
	unsafe_unique_array<sel_t> prenest_append_sel_data;
};

} // namespace duckdb
