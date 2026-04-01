# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands

```bash
make release          # Optimized production build → build/release/
make debug            # Debug build with symbols → build/debug/
make reldebug         # Release with debug info
GEN=ninja make debug  # Use Ninja for faster incremental builds
```

Key build variables:
- `DISABLE_UNITY=1` — Disable unity builds (slower but aids debugging)
- `DISABLE_SANITIZER=1` — Disable AddressSanitizer/UBSan
- `BUILD_EXTENSIONS="parquet;json;icu"` — Build specific extensions

## Testing

```bash
make unit             # Fast unit tests (~1 min), uses debug build
make allunit          # All unit tests (~1 hour), uses release build

# Run a single test by filter
build/debug/test/unittest "[test_name_filter]"

# Run a specific .test file
build/debug/test/unittest test/sql/path/to/test.test
```

Tests live in `test/`. SQL-based tests use the SQLLogicTest format (`.test` files). C++ unit tests use `.cpp` files; slow tests are marked with `[.]` suffix.

## Code Formatting & Linting

Requires `clang-format==11.0.1`: `pip install clang-format==11.0.1`

```bash
make format-fix        # Auto-fix all formatting
make format-check      # Check formatting
make format-main       # Format only changes from main branch
make tidy-check-diff   # Run clang-tidy on diff against origin/main
make tidy-fix          # Auto-fix tidy issues
```

## Architecture

DuckDB is a vectorized, columnar, in-process analytical SQL database. Query execution follows this pipeline:

```
SQL Text
  → [Parser]     src/parser/          Parse tree (SQLStatement, Expression)
  → [Planner]    src/planner/         Logical plan (LogicalOperator tree)
  → [Optimizer]  src/optimizer/       Optimized logical plan
  → [Execution]  src/execution/       Physical plan + vectorized execution
  → [Storage]    src/storage/         Columnar data, WAL, buffer management
```

**Key components:**

- **`src/main/`** — Entry points: `DatabaseInstance`, `Connection`, `ClientContext`. Start here when tracing a query end-to-end.
- **`src/parser/`** — Wraps libpg_query (PostgreSQL parser). Produces `SQLStatement`/`Expression`/`TableRef` objects.
- **`src/planner/`** — `Binder` resolves symbols via `Catalog`; outputs `LogicalOperator` tree.
- **`src/optimizer/`** — Rule-based and cost-based optimizations (predicate pushdown, join ordering, etc.).
- **`src/execution/`** — `PhysicalPlanGenerator` converts logical → physical plan. Push-based, vectorized execution via `PhysicalOperator` tree driven by `Executor`.
- **`src/catalog/`** — Manages tables, schemas, and functions; used by the planner for symbol resolution.
- **`src/storage/`** — Columnar block storage, buffer manager, WAL, and MVCC data.
- **`src/transaction/`** — Transaction lifecycle and MVCC.
- **`src/function/`** — Scalar and aggregate function implementations.
- **`src/common/`** — Shared utilities: types, vectors, exceptions, serialization.
- **`extension/`** — Plugin system. Built-in extensions: `parquet`, `json`, `icu`, `jemalloc`, `tpch`, `tpcds`, `core_functions`.

**Execution model:** push-based (operators push data downstream), vectorized (data processed in chunks, not row-at-a-time), columnar storage.

## C++ Conventions

- Use `unique_ptr` over `shared_ptr`; no raw `new`/`delete`/`malloc`
- Use `idx_t` instead of `size_t` for indices
- Use `const` liberally; use `override`/`final` on virtual methods
- No namespace `using` statements; use `std::` prefix explicitly
- All code in `duckdb` namespace
- Types: `CamelCase`; variables/files: `snake_case`
- Always use braces for `if`/loops
- Max line length: 120 columns; indentation: tabs
- No commented-out code in commits
