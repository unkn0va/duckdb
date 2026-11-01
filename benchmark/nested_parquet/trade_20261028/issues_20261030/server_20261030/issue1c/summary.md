# 이슈 1: Unnest 오버헤드 분해 (issue1c)

```
date:     2026-10-31T10:01:36+00:00
host:     apache10, 40 hardware threads, 125 GiB memory
cpu:      Intel(R) Xeon(R) Gold 5215 CPU @ 2.50GHz
uptime:    10:01:37 up 2 days, 16:55,  2 users,  load average: 0.00, 0.00, 0.00
base:     v2.1.0-dev88383 a809d3cd51  /home/layun03/nested-bench/duckdb_base/build/release/duckdb
prenest:  v2.1.0-dev88385 fabde05fe6  /home/layun03/nested-bench/duckdb_prenest_base/build/release/duckdb
final:    v2.1.0-dev88410 2d6066fd4d  /home/layun03/nested-bench/duckdb_rey/build/release/duckdb
perf:     perf version 6.8.12  (sudo perf)
scripts:  41cee15caed nested_parquet: trade issues 1-2 wrap-up, branch-miss and q4_two build-side scripts
data:     /home/layun03/nested-bench/duckdb_rey/benchmark/nested_parquet/trade_20261028/data/full
runs:     10, perf 1000 Hz
```

## 1-2 파라미터별 분해 (1스레드, perf)

### 리스트와 원소 수 (base EXPLAIN ANALYZE와 파일)

| 쿼리 | 열 | 리스트 (파일 행) | 원소 (파일) | 스캔이 낸 리스트 | UNNEST 원소 | 통과 원소 |
|---|---|---|---|---|---|---|
| q6_group | legs | 100,000,000 | 349,900,000 | 100,000,000 | 349,900,000 | 174,970,000 |
| q7_csa | legs | 100,000,000 | 349,900,000 | 28,000 | 82,000 | 82,000 |
| q7_plots | legs | 100,000,000 | 349,900,000 | 100,000,000 | 349,900,000 | 349,900,000 |

### 범주별 CPU 초, 새 기준(call stack)

| 쿼리 | 구성 | wall | CPU | 디코드 | 조립 | UNNEST | 원소 | 키 | join | 집계 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| q6_group | base | 22.96 | 23.43 | 5.57 | 11.23 | 3.03 | 1.70 | · | 0.04 | 0.76 | 1.11 |
| q6_group | prenestoff | 16.83 | 17.24 | 2.17 | 8.54 | 3.04 | 1.70 | · | 0.05 | 0.77 | 0.97 |
| q6_group | prenest | 13.04 | 13.57 | 2.22 | 5.58 | 2.82 | 1.39 | · | 0.04 | 0.69 | 0.81 |
| q6_group | flat | 26.00 | 26.00 | 3.08 | · | · | 0.80 | 4.53 | 16.44 | 0.94 | 0.21 |
| q6_group | pureflat | 26.07 | 28.37 | 10.05 | · | · | 1.48 | · | 15.07 | 0.96 | 0.81 |
| q7_csa | base | 11.37 | 11.82 | 5.56 | 5.54 | 0.07 | 0.06 | · | 0.08 | · | 0.51 |
| q7_csa | prenestoff | 6.93 | 7.29 | 2.29 | 4.30 | 0.05 | 0.05 | · | 0.07 | · | 0.53 |
| q7_csa | prenest | 6.81 | 7.18 | 2.24 | 4.25 | 0.05 | 0.06 | · | 0.05 | · | 0.53 |
| q7_csa | flat | 11.13 | 11.14 | 2.43 | · | · | 0.11 | 4.47 | 3.95 | · | 0.18 |
| q7_csa | pureflat | 7.69 | 9.97 | 7.87 | · | · | 0.36 | · | 1.10 | · | 0.64 |
| q7_plots | base | 40.35 | 40.90 | 5.72 | 11.25 | 2.90 | 0.30 | · | 9.91 | 9.32 | 1.50 |
| q7_plots | prenestoff | 34.30 | 34.76 | 2.42 | 8.45 | 3.13 | 0.26 | · | 9.96 | 9.06 | 1.47 |
| q7_plots | prenest | 34.15 | 34.60 | 2.28 | 7.79 | 3.08 | 0.25 | · | 10.07 | 9.06 | 2.09 |
| q7_plots | flat | 93.64 | 93.65 | 2.67 | · | · | 0.51 | 4.47 | 56.84 | 28.35 | 0.82 |
| q7_plots | pureflat | 97.21 | 100.53 | 9.14 | · | · | 1.63 | · | 58.05 | 29.08 | 2.63 |

### 범주별 CPU 초, 옛 기준(잎 함수 이름)

| 쿼리 | 구성 | wall | CPU | 디코드 | 조립 | 키 | FILTER | UNNEST | join | 집계 | 식·벡터 | 기타 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q6_group | base | 22.96 | 23.43 | 3.19 | 2.04 | · | · | 2.56 | · | 0.48 | 9.65 | 5.50 |
| q6_group | prenestoff | 16.83 | 17.24 | 1.10 | 1.80 | · | · | 2.60 | · | 0.51 | 7.32 | 3.91 |
| q6_group | prenest | 13.04 | 13.57 | 1.10 | 2.19 | · | 0.08 | 2.55 | · | 0.50 | 4.32 | 2.83 |
| q6_group | flat | 26.00 | 26.00 | 1.33 | · | 4.52 | 0.64 | · | 9.41 | 2.67 | 2.33 | 5.09 |
| q6_group | pureflat | 26.07 | 28.37 | 3.90 | · | · | 0.21 | · | 9.43 | 2.58 | 3.50 | 8.74 |
| q7_csa | base | 11.37 | 11.82 | 3.21 | 1.54 | · | 0.01 | 0.01 | 0.02 | 0.01 | 3.68 | 3.33 |
| q7_csa | prenestoff | 6.93 | 7.29 | 1.18 | 1.37 | · | 0.02 | 0.01 | 0.02 | 0.01 | 2.69 | 1.99 |
| q7_csa | prenest | 6.81 | 7.18 | 1.19 | 1.34 | · | 0.01 | 0.01 | 0.02 | · | 2.61 | 2.01 |
| q7_csa | flat | 11.13 | 11.14 | 1.28 | · | 4.47 | · | · | 2.69 | 0.01 | 1.15 | 1.55 |
| q7_csa | pureflat | 7.69 | 9.97 | 3.75 | · | · | 0.15 | · | 0.68 | · | 0.73 | 4.66 |
| q7_plots | base | 40.35 | 40.90 | 3.29 | 2.02 | · | 0.01 | 2.47 | 6.31 | 3.54 | 11.26 | 12.00 |
| q7_plots | prenestoff | 34.30 | 34.76 | 1.20 | 1.78 | · | 0.01 | 2.62 | 6.31 | 3.52 | 8.95 | 10.36 |
| q7_plots | prenest | 34.15 | 34.60 | 1.15 | 1.80 | · | 0.01 | 2.60 | 6.45 | 3.66 | 8.76 | 10.18 |
| q7_plots | flat | 93.64 | 93.65 | 1.33 | · | 4.42 | · | · | 25.92 | 18.07 | 7.05 | 36.86 |
| q7_plots | pureflat | 97.21 | 100.53 | 3.82 | · | · | 0.04 | · | 25.95 | 18.91 | 8.31 | 43.49 |

### 원소당·리스트당 비용 (ns)

범주 시간을 다섯 가지 단위 수로 나눈 값의 평균과, 쿼리 사이의 변동계수 CV(표준편차/평균)입니다.
비용이 그 단위에 비례하면 단위당 비용이 쿼리마다 같아 CV가 작습니다. 판단 = CV가 가장 작은 단위.
단위 수는 위 표의 값이고 flat·pure flat에도 같은 수를 씁니다. 0.01초 미만인 칸은 뺍니다.

| 구성 | 범주 | 쿼리 수 | 파일 리스트 ns (CV) | 스캔한 리스트 ns (CV) | 파일 원소 ns (CV) | 펼친 원소 ns (CV) | 통과 원소 ns (CV) | 판단 |
|---|---|---|---|---|---|---|---|---|
| base | 값 디코드 | 3 | 56.2 (0.01) | 66226.0 (1.41) | 16.1 (0.01) | 22611.7 (1.41) | 22617.0 (1.41) | 파일 원소 |
| base | 리스트 조립 | 3 | 93.4 (0.29) | 66029.1 (1.41) | 26.7 (0.29) | 22542.3 (1.41) | 22553.0 (1.41) | 파일 리스트 |
| base | UNNEST | 3 | 20.0 (0.68) | 900.7 (1.37) | 5.7 (0.68) | 306.5 (1.38) | 309.3 (1.36) | 파일 리스트 |
| base | 원소 다루기 | 3 | 6.9 (1.05) | 720.9 (1.39) | 2.0 (1.05) | 245.8 (1.40) | 247.4 (1.38) | 파일 리스트 |
| base | join | 3 | 33.4 (1.39) | 926.0 (1.34) | 9.6 (1.39) | 314.4 (1.35) | 314.4 (1.35) | 스캔한 리스트 |
| prenestoff | 값 디코드 | 3 | 22.9 (0.04) | 27298.3 (1.41) | 6.6 (0.04) | 9320.5 (1.41) | 9322.6 (1.41) | 파일 리스트 |
| prenestoff | 리스트 조립 | 3 | 71.0 (0.28) | 51258.0 (1.41) | 20.3 (0.28) | 17499.6 (1.41) | 17507.7 (1.41) | 파일 리스트 |
| prenestoff | UNNEST | 3 | 20.8 (0.69) | 651.0 (1.35) | 5.9 (0.69) | 221.1 (1.36) | 224.0 (1.33) | 파일 리스트 |
| prenestoff | 원소 다루기 | 3 | 6.7 (1.09) | 607.3 (1.39) | 1.9 (1.09) | 207.0 (1.40) | 208.6 (1.38) | 파일 리스트 |
| prenestoff | join | 3 | 33.6 (1.39) | 827.7 (1.33) | 9.6 (1.39) | 280.8 (1.34) | 280.8 (1.34) | 스캔한 리스트 |
| prenest | 값 디코드 | 3 | 22.5 (0.01) | 26733.9 (1.41) | 6.4 (0.01) | 9127.8 (1.41) | 9129.9 (1.41) | 파일 원소 |
| prenest | 리스트 조립 | 3 | 58.7 (0.25) | 50633.1 (1.41) | 16.8 (0.25) | 17286.9 (1.41) | 17292.2 (1.41) | 파일 리스트 |
| prenest | UNNEST | 3 | 19.8 (0.69) | 564.5 (1.34) | 5.7 (0.69) | 191.7 (1.35) | 194.3 (1.32) | 파일 리스트 |
| prenest | 원소 다루기 | 3 | 5.7 (1.04) | 753.4 (1.40) | 1.6 (1.04) | 257.0 (1.40) | 258.3 (1.39) | 파일 리스트 |
| prenest | join | 3 | 33.9 (1.40) | 591.6 (1.30) | 9.7 (1.40) | 200.1 (1.31) | 200.2 (1.31) | 스캔한 리스트 |
| flat | 값 디코드 | 3 | 27.3 (0.10) | 28935.8 (1.41) | 7.8 (0.10) | 9879.5 (1.41) | 9882.4 (1.41) | 파일 리스트 |
| flat | 원소 다루기 | 3 | 4.7 (0.60) | 1307.9 (1.41) | 1.3 (0.60) | 446.4 (1.41) | 447.1 (1.40) | 파일 리스트 |
| flat | 키 생성 | 3 | 44.9 (0.01) | 53282.6 (1.41) | 12.8 (0.01) | 18192.4 (1.41) | 18196.7 (1.41) | 파일 원소 |
| flat | join | 3 | 257.4 (0.88) | 47242.1 (1.40) | 73.6 (0.88) | 16117.9 (1.41) | 16133.5 (1.40) | 파일 리스트 |
| pureflat | 값 디코드 | 3 | 90.2 (0.10) | 93740.8 (1.41) | 25.8 (0.10) | 32005.5 (1.41) | 32015.1 (1.41) | 파일 리스트 |
| pureflat | 원소 다루기 | 3 | 11.5 (0.49) | 4241.7 (1.41) | 3.3 (0.49) | 1447.8 (1.41) | 1449.2 (1.41) | 파일 리스트 |
| pureflat | join | 3 | 247.4 (0.98) | 13392.9 (1.38) | 70.7 (0.98) | 4559.6 (1.38) | 4574.0 (1.38) | 파일 원소 |

## 옛 기준 → 새 기준

같은 perf 샘플을 두 기준으로 나눴습니다. 옛 기준은 잎 함수의 전체 이름(인자 포함)만 보고(`../../profile_breakdown.py`),
새 기준은 call stack을 위로 따라갑니다(`categories.py`). 행 = 옛 열, 열 = 새 범주, 값 = CPU 초.

### 모든 실행: 옛 '식·벡터'가 가는 곳 (상위 3개 새 범주)

| 폴더 | 쿼리 | 구성 | 옛 식·벡터 초 | 새 범주 (초) |
|---|---|---|---|---|
| params | q6_group | base | 9.65 | 조립 7.43, 원소 1.16, 기타 0.34 |
| params | q6_group | prenestoff | 7.32 | 조립 5.37, 원소 1.18, UNNEST 0.31 |
| params | q6_group | prenest | 4.32 | 조립 2.75, 원소 1.09, UNNEST 0.18 |
| params | q6_group | flat | 2.33 | join 1.48, 디코드 0.56, 원소 0.14 |
| params | q6_group | pureflat | 3.50 | join 1.39, 원소 1.15, 디코드 0.76 |
| params | q7_csa | base | 3.68 | 조립 3.25, 디코드 0.30, 기타 0.07 |
| params | q7_csa | prenestoff | 2.69 | 조립 2.30, 기타 0.19, 디코드 0.15 |
| params | q7_csa | prenest | 2.61 | 조립 2.27, 기타 0.16, 디코드 0.14 |
| params | q7_csa | flat | 1.15 | join 0.50, 디코드 0.45, 원소 0.11 |
| params | q7_csa | pureflat | 0.73 | 디코드 0.50, join 0.08, 기타 0.08 |
| params | q7_plots | base | 11.26 | 조립 7.49, join 2.38, 기타 0.50 |
| params | q7_plots | prenestoff | 8.95 | 조립 5.08, join 2.41, 기타 0.69 |
| params | q7_plots | prenest | 8.76 | 조립 4.59, join 2.31, 기타 1.18 |
| params | q7_plots | flat | 7.05 | join 5.20, 기타 0.51, 원소 0.46 |
| params | q7_plots | pureflat | 8.31 | join 5.39, 원소 1.42, 기타 0.55 |

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

실행 15개. 잘린 스택: 중앙값 27.7%, 최댓값 94.4%. 그중 나눠 준 것(확정 프레임 없음): 중앙값 4.0%, 최댓값 7.9%.

나눠 준 것이 5%를 넘는 실행:

| 폴더 | 쿼리 | 구성 | 나눠 준 샘플 | 잘린 샘플 (전체) | 기타/잘린 스택으로 남은 것 |
|---|---|---|---|---|---|
| params | q6_group | prenestoff | 7.9% | 85.7% | 0.72% |
| params | q7_csa | prenest | 7.1% | 8.1% | 0.47% |
| params | q7_csa | prenestoff | 7.0% | 8.4% | 0.32% |
| params | q6_group | prenest | 5.5% | 80.6% | 0.46% |
| params | q6_group | pureflat | 5.3% | 5.8% | 0.22% |

### '기타'가 10%를 넘는 실행

없음.


