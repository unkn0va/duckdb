# Nested filter pushdown — port plan (DataFusion → DuckDB fork)

Target tree: `/home/layun03/filter_wt`, branch `filter_pushdown` @ `58a44bb203`
Upstream base: `main` @ `83ae79e5b7`
Reference: `/home/layun03/datafusion_research`, branch `nested_filter_pushdown` @ `310978d22` (read-only)

## 0. Orientation notes (read this first)

Two facts changed the shape of this plan and should be settled before any code is written.

**0.1 — The invocation CWD was the reference repo, not the fork.** The task described the CWD as the
pruning fork; it is actually the DataFusion reference. The pruning work was located in the DuckDB
worktrees and verified present (§B.0). No work was lost, but the paths in the task prompt were
placeholders and never substituted.

**0.2 — The physical layer you want to port first is not in the DataFusion repo.**
`datafusion/datasource-parquet/src/nested/prenest_specs.rs` imports
`parquet::arrow::{PrenestFilterSpec, PrenestPredicateFn}` and
`nested/opener.rs` calls `builder.with_prenest_filter(spec)`. Neither symbol is upstream `parquet`.
The workspace `Cargo.toml:159` pins `parquet = { path = "../arrow-rs-flat/parquet", version = "55.2.0" }`,
and **`/home/layun03/arrow-rs-flat` does not exist on this machine.** A filesystem-wide search for
`PrenestArrayReaderBuilder` / `PrenestFilterSpec` finds only the four caller-side files in
`datafusion_research` (plus Claude session logs). There is no vendored copy and no cargo-registry copy.

Consequence: the DataFusion tree gives you the **interface contract** for the single-pass filtered
list reader, and nothing of its body. The def-level/rep-level fusion algorithm — the thing you
explicitly said you port first — has to be reconstructed, not transliterated. That is the single
largest risk in this port (§Risks R1). Recovering `arrow-rs-flat` (it is a sibling checkout of a
patched arrow-rs; check other machines, or the remote that `datafusion-nested` was built against)
would remove that risk entirely and is worth doing before committing to the schedule below.

---

# TASK A — the DataFusion design

## A.0 Commit range

`nested_projection_pushdown` (`c1faf68f4`) is an ancestor of `nested_filter_pushdown` (`310978d22`).
The merge-base with the fork's main branch `flat` is `ba9ebf058`. The *filter* feature is therefore
exactly `c1faf68f4..310978d22`:

| commit | subject |
|---|---|
| `1b449eaca` | Fix FileScanConfigBuilder losing nested_projection during physical optimizer rebuild |
| `c570c6603` | Row-group level nested predicate pushdown for unnest queries |
| `bccf2dae6` | Logical plan support for nested filter pushdown |
| `35772ba82` | UnnestExec runtime for absorbed element-level filters |
| `de39e9c2a` | Wire FileScanConfig.nested_filters into parquet prenest reader |
| `310978d22` | Element-level nested filter runtime in UnnestExec (N-level rebuild) |

(plus four benchmark/snapshot-only commits). Source diff: 34 files, +2455/−1350. Note `c570c6603`
introduced a row-group-statistics pruning path in `pruned/opener.rs` that `bccf2dae6` then **deleted**
(−175 lines); only `NestedPruningMetrics` survives from it. Do not port that dead path.

## A.1 LOGICAL layer

### A.1.1 Representation — how an element predicate is carried

A new `Expr` variant, `datafusion/expr/src/expr.rs:372`:

```rust
/// A comprehension-shaped filter on a nested list column.
/// Carried as a conjunct in a Filter's predicate; semantically
/// "evaluates to true" for row-level filtering but instructs
/// the Unnest operator to apply element-level masking.
Comprehension(Box<NestedFilterBody>),
```

The body is a recursive per-depth structure, `datafusion/expr/src/logical_plan/plan.rs:4073`:

```rust
pub enum NestedFilterBody {
    Filter  { source: String, predicate: Expr },
    Recurse { source: String, self_predicate: Option<Expr>, inner: Box<NestedFilterBody> },
}
```

**Path/label it carries.** `source` is the *full root-relative dotted path of the list this level
iterates* — `"c_orders"` at the outer level, `"c_orders.o_lineitems"` at the inner. It is a plain
`String`, not a structured descriptor. This matters for the port: DataFusion's label is a string path
and everything downstream re-resolves it by name.

**Predicate form.** The doc comment at `plan.rs:4066-4071` is explicit and is the load-bearing
invariant of the whole design:

> The predicate expression(s), expressed in **flat** form against the element struct's leaf fields —
> `Column("l_partkey")`, not `get_field(<source>, "l_partkey")`. This means the predicate is
> evaluable against a mini-batch built from the element struct's columns, with no `get_field`
> indirection at runtime.

So the predicate is *already rebased* onto the element struct's own schema at logical time. Every
runtime consumer (both the UnnestExec path and the reader path) just builds a `RecordBatch` from the
element struct's columns and calls `evaluate`. Porting this invariant is more important than porting
any single function.

The semantics are declared as: it "evaluates to true" for row-level purposes. It never removes a
top-level row — matching your stated goal that top-level cardinality is unchanged.

### A.1.2 Rules that move it down

**`PushDownFilter`** (`datafusion/optimizer/src/push_down_filter.rs`) gains three flags, all
defaulting to `false` so `SessionContext::new()` stays vanilla (`push_down_filter.rs:154-165`):

| flag | effect |
|---|---|
| `nested_filter_pushdown` | master switch; rewrites unnest-referring predicates as `Expr::Comprehension` below the Unnest |
| `nested_pushdown_deep_unnest` | `true` = wrap in `Recurse` and push past outer Unnests to the bottom-most one; `false` = leave at the forming Unnest |
| `nested_pushdown_tablescan` | absorb Comprehensions that reach the TableScan into `scan.filters`; `false` keeps them for `RollUpNestedFilter` |

The `LogicalPlan::Unnest` arm (`push_down_filter.rs:906-933`) classifies each conjunct of the Filter
above an Unnest into three buckets:

- **comprehensions** — already an `Expr::Comprehension(_)` from a deeper Unnest; wrap in `Recurse` (deep) or hold (shallow).
- **binders** — references *this* Unnest's output column (`unnest.list_type_columns[..].output_column`); becomes a freshly-formed `Filter`-shape Comprehension bound to this Unnest's list.
- **passthroughs** — unrelated to this Unnest; flow below unchanged.

`Expr::Comprehension` is added to the "can evaluate" set at `push_down_filter.rs:320` so it does not
abort pushdown analysis.

**`RollUpNestedFilter`** (`datafusion/optimizer/src/roll_up_nested_filter.rs`, new, 193 lines) is the
inverse motion and is what makes the whole thing land somewhere executable. Runs `ApplyOrder::BottomUp`.
For each Unnest with exactly one list column and no struct columns, it walks *down* through
`Projection` / `SubqueryAlias` only (stopping at any other Unnest, TableScan, etc.) to the immediate
Filter, lifts every `Expr::Comprehension` conjunct out of it, and parks them on `Unnest.filters`.

The unwrap rule (`roll_up_nested_filter.rs:130-141`) strips exactly one binder layer, because the host
Unnest *is* that binder:
- `Filter { predicate, .. }` → push the bare `predicate`.
- `Recurse { self_predicate, inner, .. }` → push `self_predicate` (if any) as a bare `Expr`, then push `Expr::Comprehension(inner)` — one level shallower than what arrived.

Two subtleties worth carrying over: it deliberately does **not** bail when `unnest.filters` is already
non-empty (PushDownFilter is iterative and re-derives conjuncts from non-pushable disjunctions in join
filters), and it dedupes with `push_unique` on syntactic equality. It converges because once every
comprehension is on `filters`, the walker finds no comprehension Filter and returns `Transformed::no`.

**Landing site.** `Unnest.filters: Vec<Expr>` (`plan.rs:4114`), documented as "Absorbed comprehension
filters as raw `Expr::Comprehension` expressions. Set by `RollUpNestedFilter`."

**Reaching the scan.** With `nested_pushdown_tablescan`, comprehensions land in `TableScan.filters`.
`physical_planner.rs:468-493` then partitions them:

```rust
let (nested_filter_exprs, scalar_filter_exprs): (Vec<Expr>, Vec<Expr>) =
    filters.iter().cloned().partition(|e| matches!(e, Expr::Comprehension(_)));
let scalar_filters = unnormalize_cols(scalar_filter_exprs.into_iter());
let mut exec = source.scan(session_state, projection.as_ref(), &scalar_filters, *fetch).await?;
```

Scalars go through the normal `TableProvider::scan` pushdown protocol; comprehensions cannot (the
protocol has no slot for them) so they are written directly onto a cloned `FileScanConfig`:

```rust
if has_nested_filters { new_config.nested_filters = nested_filter_exprs; }
exec = DataSourceExec::from_data_source(new_config);
```

`FileScanConfig.nested_filters: Vec<Expr>` (`datafusion/datasource/src/file_scan_config.rs:210`) sits
alongside the pruning field `nested_projection: Option<HashMap<usize, HashSet<String>>>` (`:203`).
**Its doc comment still says "Inert in this commit"; that is stale** — `de39e9c2a` wired it into
`build_prenest_specs`. Don't be misled by it.

### A.1.3 Predicates that cannot reach the scan

Three distinct fallbacks, all safe-by-construction:

1. **Not absorbed at all** (`nested_filter_pushdown = false`, or the Unnest has multiple list columns / struct columns): the predicate simply stays as an ordinary `Filter` above the Unnest and executes as a normal `FilterExec`. This is the vanilla plan.
2. **Absorbed to `Unnest.filters` but not to the scan**: `UnnestExec` executes it as an element-level mask at runtime (§A.2.2). Correct, just later than ideal.
3. **Absorbed to the scan but not compilable**: `nested/projection.rs:203-207` calls `build_prenest_specs(...).unwrap_or_default()` — *any* error yields an empty spec list. `build_prenest_specs` also silently drops specs whose predicate references no column or whose target list is not found in `file_schema`. The comment is explicit: "Errors here become an empty spec list (runtime falls back to the FilterExec above)."

`physical_planner.rs:827-847` strips `Expr::Comprehension` conjuncts before building any `FilterExec`,
because their bodies reference post-unnest columns not in that Filter's schema. Serialization
(`proto/src/logical_plan/to_proto.rs`) and unparsing (`sql/src/unparser/expr.rs`) get stub arms.

## A.2 PHYSICAL layer

There are **two** physical mechanisms, and the distinction is the crux of this port.

### A.2.1 The reader path — `PrenestFilterSpec` (contract present, body MISSING)

**The contract**, fully recoverable from callers:

```rust
// parquet::arrow  (in ../arrow-rs-flat/parquet — NOT ON DISK)
pub type PrenestPredicateFn = Box<dyn FnMut(&ArrayRef) -> ParquetResult<BooleanArray> + Send>;
pub struct PrenestFilterSpec {
    pub filter_field_name: String,                                              // discriminator
    pub predicate_factory: Arc<dyn Fn() -> ParquetResult<PrenestPredicateFn> + Send + Sync>,
}
impl ParquetRecordBatchStreamBuilder {
    pub fn with_prenest_filter(self, spec: PrenestFilterSpec) -> Self;
}
```

Header comment in `nested/opener.rs:74-78` states the intent precisely:

> Element-level filter specs handed to the parquet reader. Each matches one list reader (by
> struct-child field name) and applies its predicate during decode to drop non-surviving elements
> **before they cross the reader boundary**.

**Matching.** By *discriminator field name only*. `prenest_specs.rs:141-144`: the discriminator is any
one field name referenced by the predicate; `PrenestArrayReaderBuilder` walks the list readers and
attaches the spec to the **first** list whose element struct contains a field with that name.
This is a weak, name-based binding — there is no path, no index, no level number.

**Consequence the code has to work around** (`prenest_specs.rs:50-56`):

> `prenest_builder` matches at most ONE spec per list by discriminator field name, so leaf predicates
> that target the same list must be AND-combined into a single spec before reaching the parquet
> reader — otherwise some conjuncts would silently drop.

So `build_prenest_specs` (`nested/prenest_specs.rs:45-88`) does:
1. Flatten `nested_filters` to leaf predicates — one per `NestedFilterBody::Filter` and per `Recurse.self_predicate` (`collect_leaves` / `collect_leaves_body`). **Comprehension depth structure is destroyed here.**
2. Group leaves by target list, fingerprinted by the element struct's sorted field names (`fingerprint`), resolved via `find_list_struct_with_field(file_schema, first_column_ref)` — a schema walk that returns the first list-of-struct containing that field name.
3. AND-combine within each group, then `build_spec`.

`build_spec` (`:117-160`) narrows a `level_schema` to just the predicate's referenced fields, compiles
`create_physical_expr(&predicate, &dfschema, &ExecutionProps::new())`, and closes over it in a factory.
The predicate closure (`eval_predicate_on_struct`, `:162-198`) receives the element `StructArray`,
picks columns by name (`new_null_array` for absent ones), builds a mini `RecordBatch`, evaluates, and
returns the `BooleanArray`.

**What the reader must do with the mask — and what "single pass" actually means here.**
The body is missing, but the contract pins the algorithm down almost completely:

- The closure is handed a **decoded element `StructArray`**. So the predicate's columns *are* fully decoded and materialized as an element-level array before the mask exists. "Without materializing the unfiltered array first" applies to the **enclosing `ListArray`** and to the **non-predicate payload columns**, not to the predicate columns themselves.
- The saving is therefore: (a) payload columns of eliminated elements are never assembled into the output child array, and (b) the outer `ListArray` (offsets + child) is built once, already filtered — never built full then rebuilt.
- The offsets must be recomputed from rep/def levels while the mask is consumed. `UnnestExec`'s `rewrite_list_recursive` (§A.2.2) is the *post-hoc* form of exactly this arithmetic and is the best available specification of it: per outer row, `new_len[i] = mask.slice(start_i, len_i).true_count()`, prefix-summed into new offsets, with the outer list's null buffer carried through unchanged (nulls of the outer list are preserved — an element-level filter never turns a non-null empty-able list into NULL).

**Do not over-read the "never decoded" framing.** The honest statement of the win is: predicate columns are decoded for surviving *and* non-surviving elements; payload columns and the list assembly are skipped for non-surviving elements. For a wide `LIST<STRUCT>` with a narrow predicate, that is still most of the work.

**Other reader-side wiring** (all present in the DataFusion tree, all reusable as reference):
- `nested/projection.rs:203-207` — compiles specs from `base_config.nested_filters`, `unwrap_or_default()`.
- `nested/opener.rs:243-247` — `for spec in &nested_filter_specs { builder = builder.with_prenest_filter(spec.clone()); }`, applied to `ParquetRecordBatchStreamBuilder` *before* `ProjectionMask` and *before* `row_filter::build_row_filter`.
- `nested/opener.rs:255-259` — the **pruning** side: `ProjectionMask::columns(builder.parquet_schema(), nested_column_paths)`, where paths are dotted parquet leaf paths produced by `expand_to_parquet_path` (`nested/projection.rs:43`), which inserts `list.element` segments — `"c_orders.o_orderkey"` → `"c_orders.list.element.o_orderkey"`.
- `nested/metrics.rs` — `NestedPruningMetrics { row_groups_nested_pruned: Count }`. Vestigial; the pruner it counted was deleted.
- The directory was renamed `pruned/` → `nested/` in `de39e9c2a`.

### A.2.2 The UnnestExec path — element-level rebuild (present, portable, post-materialization)

This is the fallback and the *specification* for A.2.1's arithmetic. All in
`datafusion/physical-plan/src/unnest.rs` (+882 lines over the range).

Planner side, `physical_planner.rs:2345` `build_unnest_filter(input, list_column_indices, filters, session_state)`:
- Bare scalar `Expr`s in `Unnest.filters` are AND-combined at **depth 0** (the host Unnest is the binder — `RollUpNestedFilter` stripped that layer).
- `Expr::Comprehension(body)` entries contribute deeper levels via `collect_nested_filter_depths`.
- Returns `None` (no runtime, fall back) when: multiple list columns unnested in one node, non-list outer column, or no actual predicates.

Runtime types (`unnest.rs:1270-1284`):

```rust
pub struct UnnestFilterLevel { pub predicate: Option<Arc<dyn PhysicalExpr>>, pub schema: SchemaRef }
pub struct UnnestFilter { pub outer_list_col_idx: usize, pub levels: Vec<UnnestFilterLevel> }
// levels[0] = outermost list (= outer_list_col_idx); levels.last() = innermost leaf.
```

`schema` holds only the predicate's referenced columns, fixed at planning time via `Expr::column_refs`,
so runtime is a direct name lookup (`eval_predicate_on_struct`, `unnest.rs:~1350`).

The core algorithm, `rewrite_list_recursive(list: &ListArray, levels: &[UnnestFilterLevel], depth) -> Result<Option<ListArray>>`:

1. Downcast `list.values()` to `StructArray`; bail (`Ok(None)`, → fall back) if not.
2. **Innermost first.** If `depth + 1 < levels.len()`, locate the single child column whose type is `DataType::List(_)`, recurse into it, then rebuild this depth's `StructArray` with the filtered inner list swapped in — "so our predicate sees the post-filter state". (Inner filtering can empty an inner list, which an outer predicate may then test.)
3. Evaluate this depth's predicate (if any) to a `BooleanArray` mask.
4. If `mask.false_count() > 0`: `kernels::filter::filter(&values, m)` for the child, then recompute offsets:
   ```rust
   let mut cursor = 0i32; new_offs.push(0);
   for i in 0..list.len() {
       let start = old_offs[i] as usize;
       let len = (old_offs[i+1] - old_offs[i]) as usize;
       cursor += m.slice(start, len).true_count() as i32;
       new_offs.push(cursor);
   }
   ```
   Otherwise reuse the original offsets untouched (fast path).
5. `ListArray::try_new(field, final_offsets, final_values, list.nulls().cloned())` — outer null buffer preserved verbatim.

Supporting fns: `build_batch_with_filter` (`:180`), `rebuild_filtered_struct` (`:291`),
`rebuild_filtered_list` (`:348`), `mask_is_true` (`:427`), `apply_filter` (`:473`),
`FilteredBuildResult` (`:170`). Attachment: `UnnestExec::with_filter` / `::filter`.
Tests: `test_filtered_unnest_expands_parent_mask_to_child_filter`, `test_filtered_unnest_three_levels`.

**This is post-materialization.** The unfiltered `ListArray` exists, then is rebuilt. It is the
correctness oracle for the reader path, not a substitute for it.

---

# TASK B — inventory of the existing pruning implementation in this fork

## B.0 Verification

`main...HEAD` is 8 commits, +2288/−14 across 71 files. Excluding the `nested_queries_*` benchmark
directories, the change is **six files**:

```
M src/optimizer/remove_unused_columns.cpp                    +128 −5
M src/include/duckdb/optimizer/remove_unused_columns.hpp        +8
M src/common/multi_file/multi_file_column_mapper.cpp          +75 −9
M src/include/duckdb/common/multi_file/multi_file_data.hpp      +10
M src/execution/operator/scan/physical_table_scan.cpp            +7
A test/sql/copy/parquet/nested_projection_unnest.test          +130
```

The pruning work is present and coherent. Confirmed.

## B.1 How is a nested path represented?

**`ColumnIndex`**, defined at `src/include/duckdb/common/column_index.hpp:26`. It is **first-class and
pre-existing** — not introduced by the pruning work, and not an ad-hoc encoding.

```cpp
enum class ColumnIndexType : uint8_t { INVALID, FULL_READ, PUSHDOWN_EXTRACT };

struct ColumnIndex {
    bool has_index;
    idx_t index;                        // numeric position, when has_index
    string field;                       // field name, when !has_index (VARIANT)
    LogicalType type;
    ColumnIndexType index_type;
    vector<ColumnIndex> child_indexes;  // recursive
};
```

A path like `items.price` is the *tree* `ColumnIndex(items_idx, { ColumnIndex(price_idx) })`. There is
no dotted string anywhere in the descriptor — the dotted form exists only for **display**, produced by
`AddProjectionNames` in `physical_table_scan.cpp`.

**What the pruning work added to the representation:** the ability for a path to *descend through a
LIST*. `multi_file_data.hpp:70-79`, in `MultiFileColumnDefinition::CreateFromNameAndType`:

```cpp
} else if (type.id() == LogicalTypeId::LIST) {
    // recursively create for the list element. this is what allows nested sub-field projection
    // to descend through a LIST: MapColumn() treats a column with no children as a leaf and
    // drops the requested child indexes, so without an element child the reader would fall
    // back to reading the entire list.
    result.children.push_back(CreateFromNameAndType("list", ListType::GetChildType(type)));
}
```

The `"list"` name is explicitly a placeholder — element levels are matched **positionally**, because
the schema name is writer-dependent (`"list"`/`"element"` for parquet-mr≥2 and DuckDB, `"array"` for
Avro/Thrift writers, `"<name>_tuple"` for legacy parquet-mr). By convention **a list element is always
child index 0**.

Display support, `physical_table_scan.cpp:300-306`: `AddProjectionNames` recurses into `LIST` and
**omits the list level from the printed path**, so `items.price` displays rather than `items.list.price`.
This is what the regression test asserts against (`nested_projection_unnest.test:83-104`).

## B.2 How the path travels — optimizer to Parquet scan, every hop

| # | file | function | what happens |
|---|---|---|---|
| 1 | `src/optimizer/remove_unused_columns.cpp:325-361` | `RemoveUnusedColumns::VisitOperator`, `LOGICAL_UNNEST` arm | **New.** For each `BoundUnnestExpression`, look up `column_references[ColumnBinding(unnest.unnest_index, i)]`. If the parent needs only specific sub-fields, wrap them under the element level: `ColumnIndex element_index(0, out_entry->second.child_columns);` then `AddBinding(child_ref, std::move(element_index))`. If the unnested list is itself a sub-field (`UNNEST(struct_extract(o,'o_lineitems'))`), route via `RecordExtractWithLeafReqs`. If not remapped, `VisitExpression(&expr)` → full read. Comment: *"(This mirrors DataFusion's remap_through_unnest.)"* |
| 2 | `remove_unused_columns.cpp:235-274` | `VisitOperator`, `LOGICAL_PROJECTION` arm | **New.** Before pruning mangles indices, snapshot `deep_output_reqs: unordered_map<Expression*, vector<ColumnIndex>>` keyed by expression pointer (stable across compaction). After pruning, for each expression try `RecordExtractWithLeafReqs` then `RecordPassthroughWithReqs`, else fall through to `VisitExpression`. This is what carries deep requirements across a projection. |
| 3 | `remove_unused_columns.cpp:922-942` | `BaseColumnPruner::RecordExtractWithLeafReqs` | **New.** Walk the `get_field` chain via `HandleExtractRecursive`, attach the caller's `leaf_child_columns` at the **leaf** of the extract path, `AddBinding(*colref, path.GetChildIndex(0))`, then `DisablePushdownExtract(colref->binding)`. |
| 4 | `remove_unused_columns.cpp:944-958` | `BaseColumnPruner::RecordPassthroughWithReqs` | **New.** A projection expression that is a bare `BOUND_COLUMN_REF` forwards its output's requirements verbatim onto the referenced column. Comment: *"mirrors DataFusion's add_passthrough"*. |
| 5 | `remove_unused_columns.cpp:960-968` | `BaseColumnPruner::DisablePushdownExtract` | **New.** Sets `supports_pushdown_extract = PushdownExtractSupport::DISABLED`. Necessary because recorded paths can be multi-level, which the pushdown-extract rewrite cannot express. |
| 6 | `remove_unused_columns.cpp:995-1004` | `BaseColumnPruner::MergeChildColumns` | **Changed.** Was `D_ASSERT(new_child_column.ChildIndexCount() == 1); MergeChildColumns(..., GetChildIndex(0));`. Now loops **all** grandchildren, because the UNNEST pruner attaches sibling requirements under one level at once (`ColumnIndex(0, {b, c})`); merging only child 0 silently dropped the rest. |
| 7 | `remove_unused_columns.cpp:709-730` | `RemoveUnusedColumns::VisitOperator`, `LOGICAL_GET` (pre-existing) | The requirements become the scan's column list: `ColumnIndex new_index(logical_column_id.GetPrimaryIndex(), entry->second.child_columns); new_column_ids.emplace_back(...)`, written into `LogicalGet::GetMutableColumnIds()`. |
| 8 | `src/execution/operator/scan/physical_table_scan.cpp:297-306` | `AddProjectionNames` | **Changed (display only).** Recurses through `LIST` for `EXPLAIN` output. |
| 9 | `src/common/multi_file/multi_file_column_mapper.cpp:288-296` | `MapColumnList` | **Changed.** Was `//! FIXME: is this expected for lists??`. Now consumes `global_index.GetChildIndexes()` into `selected_children`, keyed by `GetPrimaryIndex()` (always 0). Unselected children get `BoundConstantExpression(Value(type))` — a NULL. |
| 10 | `multi_file_column_mapper.cpp:314-320` | `MapColumnList` → `MapColumn` | **Changed.** Passes `forced_local_index = 0` so the element level is resolved by position, not by name. |
| 11 | `multi_file_column_mapper.cpp:575-590` | `MapColumn` | **Changed.** New `forced_local_index` parameter short-circuits `mapper.Find(global_column)`. |
| 12 | `multi_file_column_mapper.cpp:207-224, 332` | `RewriteListElementSourceName` | **New.** `remap_struct` always names the element level `"list"` regardless of the file's schema; rewrites the generated mapping's source name so files whose element level is called `"array"` don't fail with *"Source value <name> not found"*. |
| 13 | `multi_file_column_mapper.cpp:200-205, 256-260` | `MatchesChildrenPositionally` / `IsTriviallyMappable` | **New/changed.** Adds `match_positionally` so the fast "identical column" path also handles LIST elements by position. |
| 14 | `extension/parquet/parquet_reader.cpp:406-441` | `ParquetReader::CreateReaderRecursive` | **UNCHANGED.** `if (indexes.empty())` build all children, else only `indexes[i].GetPrimaryIndex()` children, recursing with `indexes[i].GetChildIndexes()`. Then `ListColumnReader` / `StructColumnReader`. |

Hop 14 is the whole point: the narrowing was achieved **entirely by feeding pre-existing reader
machinery a shorter list.**

## B.3 Which Parquet reader code was touched, and how

**None.** `git diff --name-status main...HEAD` lists zero files under `extension/parquet/`. The parquet
extension is in-tree (`extension/parquet/`), not a submodule, so this is not an artifact of the diff scope.

Your expectation is exactly right:

- **"The reader receives a narrower column list"** — yes, and that is 100% of it. The mechanism is
  `ParquetReader::CreateReaderRecursive`'s pre-existing `indexes` walk (hop 14). Feeding it a
  `ColumnIndex` that descends into a LIST element causes `ListColumnReader` to be constructed with a
  `StructColumnReader` child holding only the requested leaves. Unrequested leaves get no
  `ColumnReader` at all, so their column chunks are never opened.
- **"The reader executes new logic"** — none whatsoever. The only reason any core file outside the
  optimizer changed is that the *plumbing between* the optimizer and the reader (`MultiFileColumnMapper`,
  `MultiFileColumnDefinition`) previously refused to descend through a LIST and silently degraded the
  request to a full read.

## B.4 Can the path descriptor carry a predicate?

**No. It is strictly a "which subfield to read" selector.** Evidence, all from `column_index.hpp`:

1. **No expression-shaped field exists.** Members are `has_index`, `index`, `field`, `type`,
   `index_type`, `child_indexes`. `index_type` is a 2-valued enum (`FULL_READ`, `PUSHDOWN_EXTRACT`);
   both describe *emission*, not selection of values.
2. **It is used as a map key.** `column_index_map<idx_t> child_map` in
   `remove_unused_columns.cpp:657`. `operator==` (`:47-77`) compares `has_index`, `index`/`field`,
   `type`, `index_type` and recurses over all `child_indexes` — a `unique_ptr<Expression>` member
   would be neither copyable-comparable nor hashable without inventing expression equality/hashing at
   this layer.
3. **`operator<` (`:82-85`) compares `index` only** and carries a `//! FIXME: does it make sense to
   check children here?`. The ordering is already known-shaky; hanging predicate semantics off it
   would be unsound.
4. **It is copied by value everywhere** — `vector<ColumnIndex>` passed and stored throughout
   `MapColumn`, `CreateReaderRecursive`, `LogicalGet`. A `unique_ptr<Expression>` member would make it
   move-only and break every one of those call sites.
5. **It is serialized** (`src/storage/serialization/serialize_nodes.cpp` includes `column_index.hpp`),
   so any new member becomes a persisted-plan compatibility concern.
6. **It is shared by every table function**, not just parquet. Adding a parquet-specific predicate
   slot to a core planner type is the wrong layering.

`SetPushdownExtractType` (`:137-169`) is the closest thing to "extra semantics on the descriptor", and
it is only a type-annotation walk. There is no room, and making room is the wrong move (see §C-a).

## B.5 How is the read set computed — and can a column be added back for a non-projection need?

**A mechanism already exists, is well-established, and is exactly the precedent you want.**
`RemoveUnusedColumns::VisitOperator`, `LOGICAL_GET` arm, `remove_unused_columns.cpp:652-706`:

```cpp
vector<idx_t> proj_sel;                       // all column_ids
for (idx_t i = 0; i < old_column_ids.size(); i++) proj_sel.push_back(i);
auto col_sel = proj_sel;                      // copy

ClearUnusedExpressions(proj_sel, get.table_index, false);   // (1) projection-only survivors

SetMode(BaseColumnPrunerMode::DISABLE_PUSHDOWN_EXTRACT);

// for every table filter, push a column binding into the column references map to prevent
// the column from being projected out
vector<unique_ptr<Expression>> filter_expressions;          // keeps the Expressions alive
for (auto &filter : get.table_filters.filters) {
    auto index = GetColumnIdsIndexForFilter(old_column_ids, filter.first);
    auto column_type = get.GetColumnType(ColumnIndex(filter.first));
    ColumnBinding filter_binding(get.table_index, index);
    auto column_ref = make_uniq<BoundColumnRefExpression>(std::move(column_type), filter_binding);
    auto filter_expr = filter.second->ToExpression(*column_ref);
    if (filter_expr->IsScalar()) filter_expr = std::move(column_ref);
    filter_expressions.push_back(std::move(filter_expr));
    VisitExpression(&filter_expressions.back());            // (2) adds to column_references
}

CheckPushdownExtract(get);
ClearUnusedExpressions(col_sel, get.table_index);           // (3) projection ∪ filter survivors
```

The pattern is: **synthesize a `BoundColumnRefExpression` for the non-projection need, turn it into an
`Expression`, and `VisitExpression` it.** That registers it in `column_references`, so it survives
`ClearUnusedExpressions`. `proj_sel` vs `col_sel` is retained precisely to distinguish "needed by the
projection" from "needed by the projection *or* a filter".

For our port this generalizes directly: a nested sub-field needed only by a nested predicate
(`items.price` where the query projects only `items.name`) is added back by constructing the same
`ColumnIndex(list_idx, {ColumnIndex(0, {price_idx})})` and feeding it through `AddBinding` in the same
window — before the final `ClearUnusedExpressions(col_sel, ...)`. **This is EXTEND, not BUILD.**

One caveat inherited from the existing code: `SetMode(DISABLE_PUSHDOWN_EXTRACT)` is set for this whole
window with the comment *"pushdown extract is disabled when a struct field is referenced by a filter,
because that would involve rewriting the existing TableFilterSet"*. Our nested filters do not go
through `TableFilterSet`, so we should be able to keep pushdown-extract enabled — but verify.

## B.6 Chunk boundaries when a list spans `STANDARD_VECTOR_SIZE`

All in `extension/parquet/reader/list_column_reader.cpp` (189 lines total, **untouched by the pruning
work**), in `ListColumnReader::ReadInternal<OP>` (`:73-160`).

The design: `ReadInternal` is templated on an **OP policy struct** — `TemplatedListReader` (real read)
and `TemplatedListSkipper` (no-op, used by `ApplyPendingSkips`). The OP supplies
`Initialize / GetOffset / HandleRepeat / HandleListStart / HandleNull / AppendVector`. **This template
seam is the natural insertion point for element filtering** (§C).

The mechanism, in order:

1. **Outer `while (!finished)` loop** (`:80`) — *"if an individual list is longer than
   STANDARD_VECTOR_SIZE we actually have to loop the child read to fill it"*.
2. **Overflow carry-in** (`:84-102`): if `overflow_child_count == 0`, zero `child_defines`/`child_repeats`
   and read `MinValue<idx_t>(STANDARD_VECTOR_SIZE, child_column_reader->GroupRowsAvailable())` values
   into `read_vector` (reset from `read_cache`). Otherwise reuse the carried-over values and set
   `overflow_child_count = 0`.
3. **The collapse loop** (`:110-146`), commented *"hard-won piece of code this, modify at your own risk"*:
   - `child_repeats_ptr[i] == MaxRepeat()` → repeats on this level → `OP::HandleRepeat(data, result_offset - 1)`, `continue`.
   - `result_offset >= num_values` → out of output space → `finished = true; break;`
   - `child_defines_ptr[i] >= MaxDefine()` → defined → `OP::HandleListStart(data, result_offset, child_idx + current_chunk_offset, 1)`
   - `== MaxDefine() - 1` → empty list → `HandleListStart(..., 0)`
   - else → NULL up the stack → `OP::HandleNull(data, result_offset)`
   - mirror `child_repeats_ptr[i]` / `child_defines_ptr[i]` into `repeat_out` / `define_out`, `result_offset++`.
4. **Append** (`:148`): `OP::AppendVector(result_out, read_vector, child_idx)` — appends exactly the
   elements consumed this iteration.
5. **Overflow carry-out** (`:152-159`): if `child_idx < child_actual_num_values && result_offset == num_values`:
   `read_vector.Slice(read_vector, child_idx, child_actual_num_values)`,
   `overflow_child_count = child_actual_num_values - child_idx`, then **shift `child_defines_ptr` /
   `child_repeats_ptr` backward by `child_idx`** so the next call starts at 0.

State lives on the reader: `overflow_child_count`, `read_vector`, `read_cache`, `child_defines`,
`child_repeats` (both sized `STANDARD_VECTOR_SIZE` in the constructor, `:174-179`).

**Porting consequence.** A filtered variant must apply the mask *between* step 2 and step 3 (mask
computed over `child_actual_num_values` elements of `read_vector`), and every one of `HandleRepeat` /
`HandleListStart` / `HandleNull` / `AppendVector` / the overflow slice must operate on
**post-filter child positions**. The `child_idx + current_chunk_offset` arithmetic in `HandleListStart`
and the backward shift in step 5 are the two places most likely to break silently.

Related existing machinery worth knowing: `ColumnReader::Filter` (`column_reader.cpp`) already
implements late materialization — `SupportsDirectFilter() && is_first_filter` → `DirectFilter` (pushes
the filter into the dictionary decoder when `encoding == ColumnEncoding::DICTIONARY` and the whole
vector is read in one go), else `Select(...)` then `ApplyFilter(...)`. The scan loop
(`parquet_reader.cpp:1443-1462`) reads filter columns first through an `AdaptiveFilter` permutation,
builds `state.sel`, then reads the remaining columns under `filter_count`. **`ListColumnReader`
overrides neither `Filter` nor `Select`**, so lists currently fall back to full `Read` + post-filter.
That is both the gap and the template.

## B.7 Build and test commands, rough times

Machine: 16 cores, 15 GB RAM, WSL2. `ccache` **not installed**. Existing `build/release` from
2026-08-24 (`CMAKE_BUILD_TYPE=Release`, `BUILD_UNITTESTS=ON`); no `build/debug`.

```bash
cd /home/layun03/filter_wt

make release                     # -> build/release/duckdb, build/release/test/unittest
make debug                       # -> build/debug/...  (needed by plain `make unittest`)
make reldebug                    # Release + symbols; best for profiling the reader
make relassert                   # Release + D_ASSERT enabled — use this for the list-reader work

# the pruning regression test
build/release/test/unittest "test/sql/copy/parquet/nested_projection_unnest.test"

# broader parquet coverage
build/release/test/unittest "[parquet]"

make unittest_release            # build/release/test/unittest   (all default tests)
make allunit                     # build/release/test/unittest "*"  (everything; slow)
```

Build times — **estimates, not measured** (I did not build during this read-only pass):
- Cold full `make release`: ~25–45 min at `-j16` without ccache.
- Incremental edit to one file in `extension/parquet/`: ~1–3 min, dominated by the ~30–60 s link of the two 50–60 MB binaries.
- Incremental edit to `src/include/duckdb/common/column_index.hpp`: **near-full rebuild** — it is included very widely. Another argument against touching `ColumnIndex` (§C-a).
- `build/release/test/unittest "[parquet]"`: a few minutes.

Recommendation: install `ccache` and set `CMAKE_CXX_COMPILER_LAUNCHER=ccache` before starting. With
the iteration count this port implies, it pays for itself on the first day.

---

# TASK C — the mapping

`REUSE` = exists here, usable as is · `EXTEND` = exists, needs a field/parameter ·
`BUILD` = must be written · `N/A` = not needed, with reason.

## C.1 Logical layer

| # | DataFusion component | DuckDB counterpart in this fork | Class | Notes / LOC |
|---|---|---|---|---|
| L1 | `Expr::Comprehension(Box<NestedFilterBody>)` (`expr.rs:372`) | *none* | **N/A** | DuckDB has no need for a self-neutral `Expression` variant. DataFusion needed one because its predicate must survive inside a `Filter`'s single `Expr` tree while pushdown analysis runs over it. In DuckDB the predicate can live in a side-channel container on the operator from the moment it is recognised (§C-a). Adding a `BoundComprehensionExpression` would force arms in every `ExpressionIterator` / serializer / binder in the tree for no gain. |
| L2 | `NestedFilterBody::{Filter, Recurse}` (`plan.rs:4073`) | *none* | **BUILD** | New `struct NestedFilter { vector<ColumnIndex> path; unique_ptr<Expression> predicate; idx_t depth; }`, recursive or flattened-by-depth. Prefer DuckDB's structural `ColumnIndex` path over DataFusion's dotted `String` — you already have the better representation (§B.1). **~70 LOC**, new `src/include/duckdb/planner/nested_filter.hpp` (+ ~40 LOC `.cpp` for copy/serialize). |
| L3 | Predicate rebased flat onto element-struct fields (`plan.rs:4066-4071`) | `BoundReferenceExpression` over the element `StructVector`'s children | **BUILD** | The load-bearing invariant. In DuckDB: rewrite the bound predicate so column refs become `BoundReferenceExpression(i)` indexing the element struct's child vectors, then execute with `ExpressionExecutor` over a `DataChunk` of those children. **~120 LOC**, new `extension/parquet/parquet_nested_filter.cpp`. |
| L4 | `Unnest.filters: Vec<Expr>` (`plan.rs:4114`) | `LogicalUnnest` (`src/include/duckdb/planner/operator/logical_unnest.hpp`) | **EXTEND** | Add `vector<NestedFilter> nested_filters;` + serialization. **~30 LOC**. |
| L5 | `PushDownFilter` Unnest arm, 3-way classify (`push_down_filter.rs:906-933`) | `src/optimizer/filter_pushdown.cpp` (+ `filter_pushdown/*.cpp`) | **BUILD** | New `FilterPushdown::PushdownUnnest`. Classify each filter into binders / passthroughs / already-nested against `LogicalUnnest`'s output bindings. **~250 LOC**, `src/optimizer/filter_pushdown/pushdown_unnest.cpp` (new). |
| L6 | `RollUpNestedFilter` rule (`roll_up_nested_filter.rs`, 193 L) | *none* | **BUILD**, but likely **smaller** | DuckDB's `FilterPushdown` is a single recursive descent that *carries* filters down, rather than DataFusion's iterative rule set that pushes a `Filter` node one step at a time. So the "push down then roll back up" round trip is largely an artifact of DataFusion's optimizer shape. In DuckDB you can attach to the `LogicalUnnest` directly during descent. **~60 LOC** if it collapses into L5; budget **~150 LOC** standalone if it does not. Re-evaluate after L5 is written. |
| L7 | `nested_filter_pushdown` / `nested_pushdown_deep_unnest` / `nested_pushdown_tablescan` flags | `DBConfig` / `ClientConfig` settings | **EXTEND** | Mirror the default-off discipline exactly. **~40 LOC** in `src/main/settings/`. |
| L8 | `optimize_nested_projections` + `nested_required_indices.rs` | `RemoveUnusedColumns` `LOGICAL_UNNEST` arm (`remove_unused_columns.cpp:325-361`) | **REUSE** | Already ported — this *is* the pruning work. |
| L9 | Read-set add-back for filter-only columns | `proj_sel` / `col_sel` + synthesized `BoundColumnRefExpression` (`remove_unused_columns.cpp:665-706`) | **EXTEND** | Mechanism exists (§B.5). Add a loop over `NestedFilter`s in the same window, calling `AddBinding` with the nested `ColumnIndex`. Check whether `SetMode(DISABLE_PUSHDOWN_EXTRACT)` still needs to apply. **~40 LOC**. |
| L10 | `TableScan.filters` absorbing comprehensions | `LogicalGet.table_filters` (`TableFilterSet`) | **EXTEND** | `TableFilterSet` is `map<idx_t, unique_ptr<TableFilter>>` keyed by top-level column index and has no notion of a nested path. Do **not** force nested filters through it. Add `vector<NestedFilter> nested_filters;` to `LogicalGet` and its bind data. **~50 LOC**. |
| L11 | `FileScanConfig.nested_filters` + builder (`file_scan_config.rs:210`) | `ParquetOptions` / `ParquetReadBindData` | **EXTEND** | The direct analogue. **~50 LOC** in `extension/parquet/include/parquet_reader.hpp` + `parquet_extension.cpp`. |
| L12 | `physical_planner.rs:468-493` partition scalar vs nested | `PhysicalPlanGenerator::CreatePlan(LogicalGet&)` (`src/execution/physical_plan/plan_get.cpp`) | **BUILD** | Copy nested filters from `LogicalGet` into the parquet bind data. **~40 LOC**. |
| L13 | proto / unparser / type-coercion stub arms | serializer arms for `NestedFilter` | **BUILD** | Only if L2 is serialized. **~60 LOC**. |
| L14 | Fallback: uncompilable predicate → `unwrap_or_default()` → FilterExec above (`nested/projection.rs:203-207`) | leave the `PhysicalFilter` in place | **BUILD** | Cheap but non-optional. The invariant must be: absorbing a predicate into the scan is only legal once the reader has *confirmed* it will apply it; otherwise the operator-level filter stays. **~30 LOC**, spread across L11/L12. |

## C.2 Physical layer

| # | DataFusion component | DuckDB counterpart in this fork | Class | Notes / LOC |
|---|---|---|---|---|
| P1 | `PrenestFilterSpec { filter_field_name, predicate_factory }` | *none* | **BUILD** | `struct ParquetNestedFilter { vector<idx_t> element_path; unique_ptr<Expression> predicate; }`. **Do not copy DataFusion's discriminator-by-field-name matching** — it is the weakest part of that design (§Risks R3). DuckDB can bind by the same positional `ColumnIndex` path the pruning work already threads to `CreateReaderRecursive`. **~60 LOC**, `extension/parquet/include/parquet_nested_filter.hpp`. |
| P2 | `build_prenest_specs` — flatten, group by list, AND-combine (`prenest_specs.rs:45-88`) | *none* | **BUILD** | Simpler here: with a real path (P1) you group by path equality instead of struct fingerprinting, and the "AND-combine or conjuncts silently drop" hazard disappears. **~90 LOC**, `extension/parquet/parquet_nested_filter.cpp`. |
| P3 | `create_physical_expr` + `eval_predicate_on_struct` mini-batch (`prenest_specs.rs:117-198`) | `ExpressionExecutor` + `DataChunk` over the element `StructVector`'s children | **BUILD** | Same shape, DuckDB primitives. Note DataFusion substitutes `new_null_array` for fields absent from the struct; DuckDB should instead **guarantee** presence via L9 (add the predicate's columns back to the read set) and hard-error otherwise. **~120 LOC**, same file as L3. |
| P4 | `ParquetRecordBatchStreamBuilder::with_prenest_filter` | `ParquetReader::CreateReaderRecursive` attaching the filter to the matching `ListColumnReader` | **EXTEND** | The `indexes` walk (`parquet_reader.cpp:426-431`) already carries the path; thread a parallel `optional_ptr<ParquetNestedFilter>` alongside and hand it to the `ListColumnReader` constructor. **~50 LOC**. |
| **P5** | **`PrenestArrayReaderBuilder` — single-pass filtered list construction (BODY MISSING)** | **`ListColumnReader::ReadInternal<OP>`** (`list_column_reader.cpp:73-160`) | **BUILD** | **The core of the port.** Add a third OP, `TemplatedFilteredListReader`, plus mask evaluation between the child read and the collapse loop. The `OP` template seam (§B.6) means the existing read/skip paths are untouched. Must handle: post-filter child offsets in `HandleListStart`, post-filter `AppendVector`, and the overflow slice + backward def/rep shift. **~220 LOC** in `extension/parquet/reader/list_column_reader.cpp`, **~35 LOC** in `extension/parquet/include/reader/list_column_reader.hpp`. |
| P6 | Offset recomputation (spec'd by `rewrite_list_recursive`, `unnest.rs:502+`) | folded into P5's `HandleRepeat` / `HandleListStart` | **BUILD** | In DuckDB you never build the unfiltered offsets at all — `list_entry_t.length` is incremented per surviving element instead of being prefix-summed afterward. Strictly simpler than the DataFusion version. *(Counted inside P5.)* |
| P7 | N-level / nested-list recursion (`rewrite_list_recursive` innermost-first) | recursive `ListColumnReader` nesting | **BUILD** | **Defer.** Single-level `LIST<STRUCT>` first. DataFusion's innermost-first ordering exists so an outer predicate observes post-filter inner lists; the same ordering falls out naturally from DuckDB's child-reader recursion, but the interaction with two levels of `overflow_child_count` is where this gets genuinely hard. **~150 LOC** additional, deliberately out of the first three slices. |
| P8 | `UnnestExec` element-filter runtime (`unnest.rs`, +882 L) | `PhysicalUnnest` (`src/execution/operator/unnest/physical_unnest.cpp`) | **BUILD**, deferrable | This is DataFusion's *fallback* path, not its fast path. In DuckDB the equivalent fallback already exists for free: leave the `PhysicalFilter` where it is. Only needed later if you want the "absorbed but not scan-pushable" middle tier. **~200 LOC** — **do not build in phase 1.** |
| P9 | `UnnestFilter` / `UnnestFilterLevel` + `build_unnest_filter` (`physical_planner.rs:2345`) | — | **N/A** in phase 1 | Only exists to feed P8. |
| P10 | `ProjectionMask::columns()` + `expand_to_parquet_path` (dotted `c_orders.list.element.o_orderkey`) | `ColumnIndex` tree → `CreateReaderRecursive` | **REUSE** | Already working. DuckDB's structural path is strictly better than DataFusion's string expansion — no `list`/`element`/`array`/`_tuple` naming hazard, because §B.1 resolves the element level positionally. |
| P11 | `NestedPruningMetrics { row_groups_nested_pruned }` (`nested/metrics.rs`) | — | **BUILD** | Vestigial in DataFusion (its row-group pruner was deleted in `bccf2dae6`). Build a *different, useful* one: elements-read vs elements-emitted per list reader. Without it you cannot tell reader-side elimination from operator-side elimination, and the whole benchmark is unfalsifiable. **~50 LOC**. |
| P12 | Row-group-level nested statistics pruning (`c570c6603`, later deleted) | — | **N/A** | Deleted upstream. Skip. |
| P13 | `ColumnReader::Filter` / `Select` late materialization | `column_reader.cpp` — exists, **`ListColumnReader` overrides neither** | **REUSE as pattern / EXTEND later** | Not needed for P5, but it is the precedent for how DuckDB does read-filter-read, and the natural home for a later optimization where predicate leaves are decoded before payload leaves. |

## C.3 The two explicit questions

### (a) Can `ColumnIndex` be extended to carry a predicate, or does the filter need a separate channel?

**Separate channel, alongside. Do not extend `ColumnIndex`.**

It is technically possible — you could add a `unique_ptr<Expression>` and a third `ColumnIndexType` —
but every piece of evidence points the other way (§B.4): `ColumnIndex` is value-copied throughout the
planner and reader, is a `column_index_map` key with a structural `operator==`, has an already-shaky
`operator<`, is serialized, is shared by every table function in DuckDB, and lives in a header whose
modification triggers a near-full rebuild (§B.7). Making it move-only or expression-aware would touch
hundreds of unrelated call sites for a parquet-specific feature.

The decisive argument is semantic, not mechanical: **the two things have different cardinality.**
A read-set entry is per (column, subfield) and is a set-union — `MergeChildColumns` merges siblings
and widens toward "read more". A predicate is per (list level) and is a conjunction — it narrows.
Union-merging a descriptor that carries a predicate would silently produce the wrong answer the first
time two branches of a plan requested the same subfield with different predicates. DataFusion made
the same call: `FileScanConfig` has `nested_projection` **and** `nested_filters` as two separate
fields (`file_scan_config.rs:203` and `:210`).

The channels must nevertheless be **coupled in one direction**: a predicate over `items.price` implies
`items.price` must be in the read set even when the projection does not want it. That coupling is L9
and it reuses the existing `proj_sel`/`col_sel` add-back mechanism (§B.5).

Concretely:

```
LogicalGet          : vector<ColumnIndex> column_ids       (exists — read set)
                    + vector<NestedFilter> nested_filters  (new — predicate channel)
ParquetReadBindData : same pair
CreateReaderRecursive(context, indexes, schema)
                    → CreateReaderRecursive(context, indexes, filters, schema)
```

Both are keyed by the *same* `ColumnIndex` path, which is what keeps them in sync and lets P1 bind by
path instead of DataFusion's fragile field-name discriminator.

### (b) Smallest change that measures the reader-side benefit with no new optimizer machinery

**Add a named parameter to `read_parquet` that carries an element predicate straight to
`ListColumnReader`, and implement the filtered OP behind it.** Nothing in the optimizer moves.

Rationale: the entire uncertainty in this port is P5 — whether fusing a mask into
`ReadInternal`'s collapse loop is correct across chunk boundaries, and whether it actually pays.
Every logical-layer component (L1–L14, ~900 LOC) exists only to *derive* a predicate that this
parameter lets you supply by hand.

The slice:

1. `ParquetOptions` gains `vector<ParquetNestedFilter> nested_filters` — populated by a
   `nested_filter` named parameter, e.g.
   `SELECT ... FROM read_parquet('f.parquet', nested_filter := 'c_orders.o_lineitems.l_partkey < 100')`.
   Parse with the existing parser to a `ParsedExpression`, bind against the element struct's type.
   *(~90 LOC, `extension/parquet/parquet_extension.cpp`)*
2. Bind the dotted string to a positional `ColumnIndex` path using the schema walk the pruning work
   already established, and to a `BoundReferenceExpression`-based predicate (L3/P3).
   *(~140 LOC, new `extension/parquet/parquet_nested_filter.cpp`)*
3. Thread it through `CreateReaderRecursive` to the matching `ListColumnReader` (P4). *(~50 LOC)*
4. Implement `TemplatedFilteredListReader` in `ReadInternal` (P5). *(~255 LOC)*
5. Add the elements-read / elements-emitted counters (P11). *(~50 LOC)*

**~585 LOC, four files, zero optimizer changes, zero planner changes, zero `ColumnIndex` changes.**

Measurement protocol — three runs on the same file and the same predicate:

| variant | how | measures |
|---|---|---|
| **baseline** | `SELECT ... FROM read_parquet(f) WHERE ...` (predicate as an ordinary post-UNNEST filter) | today's cost |
| **reader** | `read_parquet(f, nested_filter := '...')` | the thing you are buying |
| **pruning-only** | projection narrowed, no predicate | isolates the existing pruning win so the new number is attributable |

Sweep predicate selectivity (the `nested_queries_direct/` benches already vary this) and list width.
The hypothesis to falsify: **reader-side element filtering only pays when the payload is wide relative
to the predicate columns** — because the predicate columns are decoded either way (§A.2.1). If your
`LIST<STRUCT>` has three narrow fields and the predicate touches one, expect the win to be small; the
counters from step 5 will tell you which regime you are in before you commit to L1–L14.

This slice is also *shippable on its own* as an explicit-control feature, and it is exactly the
surface a later optimizer would target, so none of it is throwaway.

---

# Proposed implementation order

| slice | content | LOC | gate to proceed |
|---|---|---|---|
| **0** | Recover `arrow-rs-flat`, or formally accept it is gone. Install `ccache`. Capture baseline numbers on the existing benches. | ~0 | Baselines recorded. |
| **1** | **§C-b, split in two.** 1a: parameter + binding + threading (steps 1–3, ~280 LOC) with the filter *accepted and ignored* — proves plumbing without touching the hard loop. 1b: `TemplatedFilteredListReader` + counters (steps 4–5, ~305 LOC). Single-level `LIST<STRUCT>`, no nesting. | ~585 | Correct results vs baseline on the pruning regression test + new cases; **measurable** element-decode reduction. |
| **2** | Chunk-boundary hardening for 1b: lists spanning `STANDARD_VECTOR_SIZE`, all-elements-filtered lists, NULL lists, empty lists, `ApplyPendingSkips` under a filter. Build under `make relassert`. Fuzz list lengths against the unfiltered path. | ~120 | No `D_ASSERT` fires; results identical to baseline across randomized shapes. |
| **3** | Read-set coupling (L9): a predicate over a column the projection does not want must add it back. Reuses `proj_sel`/`col_sel`. Still driven by the explicit parameter. | ~40 | `SELECT items.name ... nested_filter := 'items.price < 5'` returns correct rows. |
| **4** | Descriptor + carriers (L2, L4, L10, L11, L12) — `NestedFilter` reaching parquet bind data from `LogicalGet`, still populated by hand/test hook, not by an optimizer rule. | ~240 | Physical plan / `EXPLAIN` shows the absorbed filter; results unchanged. |
| **5** | Optimizer rule (L5, L6, L7) — recognize the predicate above `LogicalUnnest` and absorb it, default-off behind a setting. Plus the L14 fallback invariant: never absorb unless the reader confirms it will apply. | ~500 | End-to-end on the `nested_queries_direct` suite with the setting on, byte-identical results with it off. |
| **6** | N-level nesting (P7). Only after 1–5 are stable. | ~150 | Three-level case matching DataFusion's `test_filtered_unnest_three_levels`. |
| **7** | Optional: `PhysicalUnnest` runtime (P8) for the absorbed-but-not-pushable tier. | ~200 | Only if slice 5 shows a meaningful population of such predicates. |

Slices 1–3 are the research result. Slices 4–7 are productization and should not start until slice 1b
produces a number worth productizing.

---

# The three risks most likely to sink this

### R1 — The reference implementation of the thing you port first does not exist on this machine.

`arrow-rs-flat` is gone (§0.2). What survives is a 244-line *caller* (`prenest_specs.rs`) and two call
sites. The def-level/rep-level fusion inside `PrenestArrayReaderBuilder` — the actual single-pass
filtered list construction — has no body you can read.

Why it sinks the port: the plan above silently assumes P5 is "port an algorithm". It is actually
"design an algorithm, guided by a contract and by `rewrite_list_recursive` as a post-hoc oracle."
That is a materially larger and riskier task, and it is the task on the critical path of every slice.

Mitigations: (1) spend slice 0 trying to recover `arrow-rs-flat` — it is a sibling checkout of a
patched arrow-rs; check other machines and whatever remote `matdulgi/datafusion-nested` was built
against. (2) Failing that, treat `rewrite_list_recursive` (§A.2.2) as the executable specification and
build slice 1b as a *differential* test against it: same input, filtered-read output must equal
read-then-`rewrite_list_recursive` output, for randomized list shapes. (3) Do not let slice 1 start
until one of these is in place.

### R2 — `ReadInternal`'s collapse loop is load-bearing, chunk-boundary state is on the reader, and the code says so.

`list_column_reader.cpp:111` — *"hard-won piece of code this, modify at your own risk"*. The loop
interleaves three coordinate systems: parquet rep/def levels, `read_vector` child positions, and
output `result_offset`. Element filtering perturbs the middle one, and the perturbation has to
propagate into `child_idx + current_chunk_offset` (the offset written into `list_entry_t`), into
`OP::AppendVector(result_out, read_vector, child_idx)`, and into the overflow carry-out — which slices
`read_vector` *and* shifts `child_defines_ptr`/`child_repeats_ptr` backward by `child_idx`
(`:152-159`). Get any one wrong and you get wrong answers, not a crash, and only for lists that happen
to straddle a vector boundary.

Why it sinks the port: silent wrong results on large lists, discovered late, in a code path where the
existing tests use three-row toy files (`nested_projection_unnest.test:8-14`). The current regression
test cannot detect this class of bug at all.

Mitigations: the `OP` template seam means you never edit the existing read/skip paths — add a third OP
rather than branching inside the shared loop. Build slice 2 under `make relassert`. Write the
randomized straddling-list fuzz *before* slice 1b, not after. Explicitly cover: a single list longer
than `STANDARD_VECTOR_SIZE`, a list where every element is filtered out, a filtered list adjacent to a
NULL list, and a filter that empties the last list in a chunk.

### R3 — The win may be small, and the benchmark as currently framed cannot tell you.

Two compounding problems. First, the mechanism is weaker than "eliminated elements are never decoded":
the predicate's own columns are decoded for every element, surviving or not (§A.2.1) — the closure
receives a decoded element `StructArray`. The saving is on payload columns and on list assembly. For a
narrow `LIST<STRUCT>`, that can approach zero. Second, this composes with pruning that **already
landed**: the existing work narrows the read set to the referenced leaves, which is precisely the
lever that shrinks the payload the new filter would have avoided decoding. The better the pruning
already works, the less the filter has left to win.

Why it sinks the port: you spend slices 1–6 and land a change whose benefit is inside the noise of the
median-of-5 harness, or — worse — one that reads as a win only because it is being compared against a
baseline with pruning off.

Mitigations: build P11's counters in slice 1b, not later — elements-read vs elements-emitted is what
distinguishes reader-side elimination from operator-side elimination. Always run the three-way
comparison in §C-b (baseline / reader / pruning-only), never two-way. Decide the go/no-go threshold
*before* slice 1b produces numbers. And sweep payload width deliberately: state up front that the
expected regime is wide payload + narrow predicate + selective filter, and report honestly if the
TPC-H-derived nested schemas do not sit in that regime.

---

# Appendix — file index

**DataFusion reference** (`/home/layun03/datafusion_research`, `310978d22`, read-only)

| file | role |
|---|---|
| `datafusion/expr/src/expr.rs:372` | `Expr::Comprehension` |
| `datafusion/expr/src/logical_plan/plan.rs:4058-4115` | `NestedFilterBody`, `Unnest.filters` |
| `datafusion/optimizer/src/push_down_filter.rs:136-165, 320, 906-933` | flags + Unnest classify arm |
| `datafusion/optimizer/src/roll_up_nested_filter.rs` | `RollUpNestedFilter` (193 L) |
| `datafusion/optimizer/src/optimize_nested_projections/{mod,nested_required_indices}.rs` | pruning (already ported) |
| `datafusion/datasource/src/file_scan_config.rs:203, 210` | `nested_projection`, `nested_filters` |
| `datafusion/core/src/physical_planner.rs:461-496, 824-847, 2336-2350` | scan absorb, Filter strip, `build_unnest_filter` |
| `datafusion/datasource-parquet/src/nested/prenest_specs.rs` | spec compilation (244 L) |
| `datafusion/datasource-parquet/src/nested/opener.rs:74-78, 238-259` | `with_prenest_filter`, `ProjectionMask` |
| `datafusion/datasource-parquet/src/nested/projection.rs:43, 197-233` | `expand_to_parquet_path`, opener construction |
| `datafusion/physical-plan/src/unnest.rs:170-600, 1270-1300` | element-filter runtime, `rewrite_list_recursive` |
| **`../arrow-rs-flat/parquet`** | **`PrenestFilterSpec`, `PrenestArrayReaderBuilder` — MISSING** |

**This fork** (`/home/layun03/filter_wt`, `58a44bb203`)

| file | role |
|---|---|
| `src/include/duckdb/common/column_index.hpp:26` | `ColumnIndex` — the path descriptor |
| `src/optimizer/remove_unused_columns.cpp:235-274, 325-361, 922-968, 995-1004` | pruning: projection arm, UNNEST arm, new helpers, merge fix |
| `src/optimizer/remove_unused_columns.cpp:652-730` | read-set computation, `proj_sel`/`col_sel` add-back |
| `src/include/duckdb/common/multi_file/multi_file_data.hpp:70-79` | LIST element child creation |
| `src/common/multi_file/multi_file_column_mapper.cpp:196-224, 288-320, 575-590` | positional element matching, `RewriteListElementSourceName` |
| `src/execution/operator/scan/physical_table_scan.cpp:300-306` | `AddProjectionNames` LIST recursion (display) |
| `extension/parquet/parquet_reader.cpp:406-441` | `CreateReaderRecursive` — **untouched**, honors narrowed `ColumnIndex` |
| `extension/parquet/reader/list_column_reader.cpp:73-160` | `ReadInternal<OP>` — **the P5 target** |
| `extension/parquet/column_reader.cpp` (`Filter`/`Select`/`DirectFilter`) | existing late-materialization precedent |
| `extension/parquet/parquet_reader.cpp:1425-1470` | scan-loop filter application, `AdaptiveFilter`, `state.sel` |
| `test/sql/copy/parquet/nested_projection_unnest.test` | pruning regression test (`EXPLAIN` REGEX assertions) |
