# 이슈 1: Unnest 오버헤드 분해 (issue1d)

```
date:     2026-11-01T13:04:31+00:00
host:     apache10, 40 hardware threads, 125 GiB memory
cpu:      Intel(R) Xeon(R) Gold 5215 CPU @ 2.50GHz
uptime:    13:04:31 up 3 days, 19:58,  2 users,  load average: 0.00, 0.00, 0.00
base:     v2.1.0-dev88383 a809d3cd51  /home/layun03/nested-bench/duckdb_base/build/release/duckdb
prenest:  v2.1.0-dev88385 fabde05fe6  /home/layun03/nested-bench/duckdb_prenest_base/build/release/duckdb
final:    v2.1.0-dev88410 2d6066fd4d  /home/layun03/nested-bench/duckdb_rey/build/release/duckdb
perf:     perf version 6.8.12  (sudo perf)
scripts:  137eeb15dc1 nested_parquet: trade, where the branch misses of prenest's q2_s50 are (sampling script)
data:     /home/layun03/nested-bench/duckdb_rey/benchmark/nested_parquet/trade_20261028/data/full
runs:     10, perf 1000 Hz
```

## 분기 miss가 생기는 곳 (perf record -e branch-misses, 1스레드)

branch-miss를 PERIOD번에 한 번씩, call stack과 함께 샘플링했습니다. 값은 miss 수(백만)이고 범주는 1-4와 같습니다.

| 쿼리 | 구성 | miss (백만) | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 | 가장 많은 잎 함수 (백만) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| q2_c25 | base | 500 | 22 | 239 | 103 | 129 | · | · | · | 6 | 원소 다루기: `string_t::StringComparisonOperators::GreaterThan` 106, UNNEST: `PhysicalUnnest::ExecuteInternal` 100, 리스트 조립: `unsigned long ListColumnReader::ReadInternal<Templ` 95 |
| q2_c50 | base | 627 | 22 | 237 | 103 | 259 | · | · | · | 6 | 원소 다루기: `string_t::StringComparisonOperators::GreaterThan` 142, UNNEST: `PhysicalUnnest::ExecuteInternal` 100, 리스트 조립: `unsigned long ListColumnReader::ReadInternal<Templ` 92 |
| q2_c50 | flat | 344 | 10 | · | · | 252 | 82 | · | · | 1 | 원소 다루기: `string_t::StringComparisonOperators::GreaterThan` 141, 키 생성: `ParquetNodeKeyGenerator::Process` 81, 원소 다루기: `unsigned long ComparisonFilterExecutor::SelectType` 78 |
| q2_c50 | prenest | 481 | 12 | 277 | 94 | 93 | · | · | · | 4 | 리스트 조립: `ListColumnReader::ReadFilteredInternal` 263, UNNEST: `PhysicalUnnest::ExecuteInternal` 79, 원소 다루기: `string_t::StringComparisonOperators::GreaterThan` 49 |
| q2_s01 | prenest | 105 | 6 | 91 | 4 | 2 | · | · | · | 2 | 리스트 조립: `ListColumnReader::ReadFilteredInternal` 85, UNNEST: `PhysicalUnnest::ExecuteInternal` 2, 리스트 조립: `VectorBuffer::Copy` 1 |
| q2_s10 | prenest | 149 | 7 | 102 | 35 | 3 | · | · | · | 2 | 리스트 조립: `ListColumnReader::ReadFilteredInternal` 96, UNNEST: `PhysicalUnnest::ExecuteInternal` 22, UNNEST: `UnnestOperatorState::PrepareInput` 12 |
| q2_s50 | base | 372 | 22 | 234 | 104 | 7 | · | · | · | 6 | UNNEST: `PhysicalUnnest::ExecuteInternal` 101, 리스트 조립: `unsigned long ListColumnReader::ReadInternal<Templ` 91, 리스트 조립: `VectorStringBuffer::CopyInternal` 85 |
| q2_s50 | prenest | 318 | 7 | 143 | 160 | 4 | · | · | · | 4 | 리스트 조립: `ListColumnReader::ReadFilteredInternal` 132, UNNEST: `PhysicalUnnest::ExecuteInternal` 107, UNNEST: `UnnestOperatorState::PrepareInput` 51 |
| q2_s50 | prenestoff | 214 | 7 | 92 | 103 | 6 | · | · | 1 | 5 | UNNEST: `PhysicalUnnest::ExecuteInternal` 100, 리스트 조립: `unsigned long ListColumnReader::ReadInternal<Templ` 79, 기타: `VectorCacheEntry::ResetFromCache` 2 |
| q2_s90 | prenest | 238 | 6 | 106 | 117 | 4 | · | · | · | 5 | UNNEST: `PhysicalUnnest::ExecuteInternal` 104, 리스트 조립: `ListColumnReader::ReadFilteredInternal` 91, UNNEST: `UnnestOperatorState::PrepareInput` 11 |

## 1-4 범주 정의

perf 샘플마다 호출 스택을 잎(샘플된 함수)에서 위로 따라가며, 아래 규칙에 처음 맞는 함수가 범주를 정합니다.
규칙에 없는 함수(memcpy·malloc, kernel, validity·벡터 도우미, 해시, tuple data, 문자열 연산)는 건너뛰고, 그것을 부른 코드의 범주를 받습니다.
'임시' 규칙(식 평가)은 위쪽에서 연산자(FILTER, PROJECTION, 스캔 필터, prenest, join, 집계)를 만나면 그 연산자를 따릅니다.
함수 이름은 인자를 뺀 이름으로 맞춥니다. 원본 스택은 `profile/*/*.folded.gz`에 있어 `categories.py classify`로 다시 나눌 수 있습니다.

| 순서 | 범주 | 세부 | 종류 | 함수 이름 패턴 (정규식, 인자 제외) |
|---|---|---|---|---|
| 1 | 원소 다루기 | prenest 조건 | 확정 | `PrenestFilter` |
| 2 | join | join 필터 | 확정 | `JoinFilterPushdown &#124; BloomFilter &#124; PrefixRange &#124; PerfectHashJoinFilter &#124; DynamicTableFilterSet &#124; PushDynamicFilters` |
| 3 | 원소 다루기 | 스캔 필터 | 확정 | `(?<![A-Za-z])ColumnReader::(Select &#124; Filter &#124; ApplyFilter) &#124; FilterSelection &#124; TableFilterState &#124; ExpressionFilter &#124; ConstantFilter &#124; ConjunctionAndFilter &#124; ConjunctionOrFilter &#124; IsNotNullFilter &#124; IsNullFilter &#124; FilterRows &#124; TemplatedFilterOperation &#124; ParquetReader::ApplyFilter &#124; ColumnReader::DirectSelect &#124; PlainSelect` |
| 4 | 리스트 조립 | list/struct reader | 확정 | `(List &#124; Struct &#124; Array)ColumnReader &#124; TemplatedListReader &#124; ListReader` |
| 5 | 키 생성 | node keys | 확정 | `ParquetNodeKeyGenerator &#124; CountPageLevelRows &#124; ParquetNodeRowGroupRows &#124; KeyRange` |
| 6 | 값 디코드 | levels/skip | 확정 | `ReadLevels &#124; SkipPageValues &#124; ApplyPendingSkips &#124; PlainSkip &#124; (?<![A-Za-z])ColumnReader::Skip &#124; RleBpDecoder` |
| 7 | 값 디코드 | decode | 확정 | `Decoder &#124; Decompress &#124; [Ss]nappy &#124; ZSTD &#124; zstd &#124; [Ll][Zz]4 &#124; brotli &#124; miniz &#124; BitpackingPrimitives &#124; ParquetDecodeUtils &#124; thrift &#124; Thrift &#124; TCompactProtocol &#124; ColumnReader &#124; ResizeableBuffer &#124; ByteBuffer &#124; DictionaryDecoder` |
| 8 | 값 디코드 | scan | 확정 | `ParquetReader &#124; ParquetScan &#124; ParquetMultiFile &#124; MultiFileFunction &#124; MultiFileReader &#124; PhysicalTableScan &#124; TableScanFunction &#124; ReadParquetNode &#124; ReadParquetFlat &#124; ParquetNodePageCache &#124; ParquetFileMetadataCache` |
| 9 | UNNEST | unnest | 확정 | `PhysicalUnnest &#124; UnnestOperator &#124; UnnestFunction` |
| 10 | join | hash join | 확정 | `PhysicalHashJoin &#124; JoinHashTable &#124; PerfectHashJoin &#124; ScanStructure &#124; PhysicalNestedLoopJoin &#124; PhysicalPiecewiseMergeJoin &#124; PhysicalIEJoin &#124; PhysicalCrossProduct &#124; PhysicalPositionalScan &#124; PhysicalRangeJoin &#124; PhysicalDelimJoin &#124; RowMatcher &#124; JoinHT` |
| 11 | 집계 | aggregate | 확정 | `PhysicalHashAggregate &#124; PhysicalUngroupedAggregate &#124; PhysicalPerfectHashAggregate &#124; RadixPartitionedHashTable &#124; GroupedAggregateHashTable &#124; PerfectAggregateHashTable &#124; AggregateExecutor &#124; AggregateFunction &#124; SumState &#124; AvgState &#124; CountStar &#124; CountFunction &#124; MinMaxState &#124; DistinctAggregate &#124; RadixHTGlobal &#124; RadixHTLocal &#124; AggregateHT` |
| 12 | 원소 다루기 | FILTER | 확정 | `PhysicalFilter` |
| 13 | 원소 다루기 | PROJECTION | 확정 | `PhysicalProjection` |
| 14 | 기타 | 정렬/limit | 확정 | `PhysicalOrder &#124; PhysicalTopN &#124; PhysicalLimit &#124; PhysicalStreamingLimit &#124; RadixSort &#124; SortedRun` |
| 15 | 기타 | 실행기/결과 | 확정 | `PipelineExecutor &#124; TaskScheduler &#124; ExecutorTask &#124; PipelineTask &#124; (?<![A-Za-z])Executor:: &#124; PhysicalResultCollector &#124; ColumnDataCollection &#124; QueryResult &#124; ClientContext &#124; duckdb_shell &#124; ShellState` |
| 16 | 원소 다루기 | 식 | 임시 (위쪽 연산자가 정함) | `ExpressionExecutor &#124; BinaryExecutor &#124; UnaryExecutor &#124; TernaryExecutor &#124; GenericExecutor &#124; ScalarFunction &#124; StructExtract &#124; ListExtract &#124; VectorCastHelpers &#124; TryCast &#124; CastFunction &#124; Comparison &#124; LikeOperator &#124; ConjunctionState` |
| - | 기타 | libc / kernel / unknown / duckdb 미분류 | 규칙 없음 | 스택 전체에 맞는 규칙이 없을 때, 잎 함수의 종류 |

### 잘린 스택

perf가 스레드 시작까지 풀지 못한 스택(맨 위 프레임이 `[heap]`·`[stack]`·`[unknown]` 주소)입니다. 두 가지가 섞여 있습니다.
- 위쪽에서 잘린 것: 16KB 스택 복사 한계에서 shell 프레임(`RunShell` 등) 위가 잘림. 연산자·리더 프레임은 남아 있어 분류에 영향이 없습니다.
- 잎 바로 위에서 잘린 것: 확정 규칙을 만나기 전에 끊김. 같은 실행에서 같은 잎 함수를 가진 온전한 샘플들의 범주 비율로 나눕니다
  (그런 샘플이 없으면 기타/잘린 스택).

### '기타'가 10%를 넘는 실행

없음.


