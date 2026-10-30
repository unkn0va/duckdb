#!/usr/bin/env python3
"""The categories of a perf sample, from its call stack (issue 1-4).

A sample is classified by walking its stack from the sampled function (the leaf) towards the root:
  - a frame that matches a STRONG rule decides the category and ends the walk;
  - a frame that matches a WEAK rule (expressions) is remembered, and the walk goes on - an operator frame further up
    (FILTER, PROJECTION, a scan filter, pre-nest, a join, an aggregate) decides where the expression was evaluated;
  - every other frame is transparent: memcpy/malloc, the kernel, vector and validity helpers, hashing, tuple data,
    string operations take the category of the code that called them.
Without a strong frame the first weak one decides; without either the sample is "기타" with the kind of its leaf.
A stack perf could not unwind to the thread's start (truncated) and without a strong frame takes the categories of
the complete stacks of the same leaf function in that run (classify_samples).
The rules match the qualified function name without its arguments (in "f(duckdb::ColumnReader &)" the argument type
does not count), first rule first within a frame.

The earlier reports used the leaf-only categories of ../../profile_breakdown.py: the sampled function's full symbol
(its arguments included) against that file's CATEGORIES, read from it here (old_classify), and grouped into the
columns of server_20261029/summary.md (OLD_GROUPS).

Usage: categories.py table                       the rules as a markdown table
       categories.py classify <folded.gz> ...    re-classify recorded stacks (profile_stacks.py) and print the
                                                 CPU ms per category and sub-category as CSV (label from the file name)
       categories.py compare <folded.gz> ...     CPU ms of every (old column, new category / sub-category) pair as CSV
"""
import ast
import collections
import gzip
import os
import re
import sys

CATEGORIES = ["값 디코드", "리스트 조립", "UNNEST", "원소 다루기", "키 생성", "join", "집계", "기타"]

# (category, sub-category, strength, regex on the function name), first match within a frame wins
RULES = [
    # the element condition inside the list reader (prenest-3way)
    ("원소 다루기", "prenest 조건", "strong", r"PrenestFilter"),
    # the filters of joins applied in a scan (bloom filters, min/max ranges) belong to the join
    (
        "join",
        "join 필터",
        "strong",
        r"JoinFilterPushdown|BloomFilter|PrefixRange|PerfectHashJoinFilter|DynamicTableFilterSet|PushDynamicFilters",
    ),
    # the query's filters evaluated by the scan, before the rows leave it
    (
        "원소 다루기",
        "스캔 필터",
        "strong",
        r"(?<![A-Za-z])ColumnReader::(Select|Filter|ApplyFilter)|FilterSelection|TableFilterState|ExpressionFilter"
        r"|ConstantFilter|ConjunctionAndFilter|ConjunctionOrFilter|IsNotNullFilter|IsNullFilter|FilterRows"
        r"|TemplatedFilterOperation|ParquetReader::ApplyFilter|ColumnReader::DirectSelect|PlainSelect",
    ),
    ("리스트 조립", "list/struct reader", "strong", r"(List|Struct|Array)ColumnReader|TemplatedListReader|ListReader"),
    ("키 생성", "node keys", "strong", r"ParquetNodeKeyGenerator|CountPageLevelRows|ParquetNodeRowGroupRows|KeyRange"),
    (
        "값 디코드",
        "levels/skip",
        "strong",
        r"ReadLevels|SkipPageValues|ApplyPendingSkips|PlainSkip|(?<![A-Za-z])ColumnReader::Skip|RleBpDecoder",
    ),
    (
        "값 디코드",
        "decode",
        "strong",
        r"Decoder|Decompress|[Ss]nappy|ZSTD|zstd|[Ll][Zz]4|brotli|miniz|BitpackingPrimitives|ParquetDecodeUtils"
        r"|thrift|Thrift|TCompactProtocol|ColumnReader|ResizeableBuffer|ByteBuffer|DictionaryDecoder",
    ),
    (
        "값 디코드",
        "scan",
        "strong",
        r"ParquetReader|ParquetScan|ParquetMultiFile|MultiFileFunction|MultiFileReader|PhysicalTableScan"
        r"|TableScanFunction|ReadParquetNode|ReadParquetFlat|ParquetNodePageCache|ParquetFileMetadataCache",
    ),
    ("UNNEST", "unnest", "strong", r"PhysicalUnnest|UnnestOperator|UnnestFunction"),
    (
        "join",
        "hash join",
        "strong",
        r"PhysicalHashJoin|JoinHashTable|PerfectHashJoin|ScanStructure|PhysicalNestedLoopJoin|PhysicalPiecewiseMergeJoin"
        r"|PhysicalIEJoin|PhysicalCrossProduct|PhysicalPositionalScan|PhysicalRangeJoin|PhysicalDelimJoin|RowMatcher"
        r"|JoinHT",
    ),
    (
        "집계",
        "aggregate",
        "strong",
        r"PhysicalHashAggregate|PhysicalUngroupedAggregate|PhysicalPerfectHashAggregate|RadixPartitionedHashTable"
        r"|GroupedAggregateHashTable|PerfectAggregateHashTable|AggregateExecutor|AggregateFunction|SumState|AvgState"
        r"|CountStar|CountFunction|MinMaxState|DistinctAggregate|RadixHTGlobal|RadixHTLocal|AggregateHT",
    ),
    ("원소 다루기", "FILTER", "strong", r"PhysicalFilter"),
    ("원소 다루기", "PROJECTION", "strong", r"PhysicalProjection"),
    ("기타", "정렬/limit", "strong", r"PhysicalOrder|PhysicalTopN|PhysicalLimit|PhysicalStreamingLimit|RadixSort|SortedRun"),
    (
        "기타",
        "실행기/결과",
        "strong",
        r"PipelineExecutor|TaskScheduler|ExecutorTask|PipelineTask|(?<![A-Za-z])Executor::|PhysicalResultCollector"
        r"|ColumnDataCollection|QueryResult|ClientContext|duckdb_shell|ShellState",
    ),
    # expressions: where they were evaluated is decided by an operator frame further up
    (
        "원소 다루기",
        "식",
        "weak",
        r"ExpressionExecutor|BinaryExecutor|UnaryExecutor|TernaryExecutor|GenericExecutor|ScalarFunction"
        r"|StructExtract|ListExtract|VectorCastHelpers|TryCast|CastFunction|Comparison|LikeOperator|ConjunctionState",
    ),
]
COMPILED = [(c, s, strength, re.compile(p)) for c, s, strength, p in RULES]


def function_name(symbol):
    """The qualified name of a demangled symbol without its argument list (and without what follows it)."""
    depth = 0
    for i, ch in enumerate(symbol):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(depth - 1, 0)
        elif ch == "(" and depth == 0 and i > 0:
            # "(anonymous namespace)" and "operator()" are part of the name
            if symbol.startswith("(anonymous namespace)", i) or symbol.endswith("operator", 0, i):
                continue
            return symbol[:i]
    return symbol


def leaf_kind(frame, dso):
    if "kernel" in dso or dso.startswith("["):
        return "kernel"
    if any(lib in dso for lib in ("libc.", "libc-", "libstdc++", "libm.", "libgcc", "ld-linux")):
        return "libc"
    if frame == "[unknown]" or not frame:
        return "unknown"
    return "duckdb 미분류"


def decide(stack):
    """(category, sub-category, decided by a strong frame) of a sample; stack = [(function name, dso), ...] from the
    leaf to the root."""
    weak = None
    for frame, _ in stack:
        for category, sub, strength, pattern in COMPILED:
            if pattern.search(frame):
                if strength == "strong":
                    return category, sub, True
                if weak is None:
                    weak = (category, sub)
                break
    if weak:
        return (*weak, False)
    frame, dso = stack[0] if stack else ("", "")
    return "기타", leaf_kind(frame, dso), False


def classify(stack):
    """(category, sub-category) of a sample from its own stack."""
    return decide(stack)[:2]


def truncated(stack):
    """Whether perf could not unwind the stack up to the start of the thread: its outermost frame is no function
    (an address in the heap, on the stack or unknown)."""
    frame, dso = stack[-1] if stack else ("[unknown]", "")
    return frame == "[unknown]" or dso in ("[heap]", "[stack]", "[unknown]", "")


def classify_samples(stacks):
    """[{(category, sub-category): share}] for the [(stack, count, ...)] of one run. A sample whose stack is cut off
    and has no strong frame below the cut takes the categories of the run's complete samples with the same leaf
    function, in their proportions; without any it is 기타 / 잘린 스택."""
    by_leaf = collections.defaultdict(collections.Counter)
    decided = []
    for stack, n, *_ in stacks:
        category, sub, strong = decide(stack)
        cut = truncated(stack)
        decided.append((category, sub, strong, cut))
        if not cut:
            by_leaf[stack[0][0]][(category, sub)] += n
    result = []
    for (stack, *_), (category, sub, strong, cut) in zip(stacks, decided):
        if strong or not cut:
            result.append({(category, sub): 1.0})
            continue
        known = by_leaf.get(stack[0][0])
        total = sum(known.values()) if known else 0
        result.append({k: v / total for k, v in known.items()} if total else {("기타", "잘린 스택"): 1.0})
    return result


def _old_rules():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "profile_breakdown.py")
    for node in ast.parse(open(path).read()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "CATEGORIES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"no CATEGORIES in {path}")


OLD_RULES = _old_rules()
# the columns of the tables in server_20261029/summary.md ("시간 분해"); every other old category is 기타
OLD_GROUPS = {
    "parquet decode": "디코드",
    "parquet levels/skip": "디코드",
    "list assembly": "조립",
    "keys": "키",
    "scan filters / late decoding": "FILTER",
    "pre-nest filter": "FILTER",
    "unnest": "UNNEST",
    "hash join": "join",
    "join filters": "join",
    "aggregate": "집계",
    "expressions": "식·벡터",
    "vectors": "식·벡터",
}
OLD_COLUMNS = ["디코드", "조립", "키", "FILTER", "UNNEST", "join", "집계", "식·벡터", "기타"]


def old_classify(symbol, dso, binary="duckdb"):
    """The column of profile_breakdown.py's category of a sample: its leaf's full symbol and file only."""
    if dso == binary:
        category = next((name for name, patterns in OLD_RULES if any(p in symbol for p in patterns)), "other duckdb")
    elif "libc" in dso or "libstdc++" in dso or "libm" in dso:
        category = "libc"
    elif "kernel" in dso:
        category = "kernel"
    else:
        category = "other"
    return OLD_GROUPS.get(category, "기타")


def table():
    print("| 순서 | 범주 | 세부 | 종류 | 함수 이름 패턴 (정규식, 인자 제외) |")
    print("|---|---|---|---|---|")
    for i, (category, sub, strength, pattern) in enumerate(RULES, 1):
        kind = "확정" if strength == "strong" else "임시 (위쪽 연산자가 정함)"
        print(f"| {i} | {category} | {sub} | {kind} | `{pattern.replace('|', ' &#124; ')}` |")
    print("| - | 기타 | libc / kernel / unknown / duckdb 미분류 | 규칙 없음 | 스택 전체에 맞는 규칙이 없을 때, 잎 함수의 종류 |")


def read_folded(path):
    """The header {"freq": hz, ...} and the [(stack from the leaf, count, the leaf's full symbol)] of a folded file of
    profile_stacks.py: a first line '# key=value ...', then 'root;...;leaf<TAB>symbol count' with frames 'name@dso'
    (files without the symbol give the leaf's name instead)."""
    header, stacks = {}, []
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                header.update(item.split("=", 1) for item in line[1:].split())
                continue
            frames, _, count = line.rstrip("\n").rpartition(" ")
            frames, _, symbol = frames.partition("\t")
            stack = []
            for frame in reversed(frames.split(";")):
                name, _, dso = frame.partition("@")
                stack.append((name, dso))
            stacks.append((stack, int(count), symbol or stack[0][0]))
    return header, stacks


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("table", "classify", "compare"):
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "table":
        table()
        return
    compare = sys.argv[1] == "compare"
    print("label,old,category,sub,cpu_ms" if compare else "label,category,sub,cpu_ms")
    for path in sys.argv[2:]:
        header, stacks = read_folded(path)
        freq = int(header.get("freq", 1000))
        label = header.get("label") or re.sub(r"\.folded\.gz$", "", os.path.basename(path))
        counts = collections.Counter()
        for (stack, n, symbol), shares in zip(stacks, classify_samples(stacks)):
            for key, share in shares.items():
                counts[(old_classify(symbol, stack[0][1]), *key) if compare else key] += n * share
        for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"{label},{','.join(key)},{n * 1000 / freq:.1f}")


if __name__ == "__main__":
    main()
