# rlm-ws

A content-addressable object store for [Recursive Language Model](https://arxiv.org/abs/2502.14155) workspaces. Think of it as Git's object model, but designed for knowledge graphs, pedagogical state tracking, and recursive LLM orchestration instead of source code versioning.

The Rust core provides the storage engine. Python bindings (via PyO3) expose the full API as a native module. Retrieval policies, model orchestration, and tutoring logic live in Python on top.

## Quickstart

### Python (recommended)

```bash
# Requires: Rust toolchain (rustup), Python 3.9+, uv
git clone <repo> && cd rlm-ws
uv sync
uv pip install maturin
uv run maturin develop
```

```python
import rlm_ws

# Create a workspace
ws = rlm_ws.Workspace.init("/tmp/my-course")

# Store content
concept = rlm_ws.Atom("ConceptDefinition", "Binary search halves the search space each step. O(log n).", tags=["algorithms"])
ch = ws.put_atom(concept)

problem = rlm_ws.Atom("ProblemStatement", "Find an element in a sorted array.")
ph = ws.put_atom(problem)

# Build structure
lesson = rlm_ws.Frame("Lesson", [
    rlm_ws.Edge("CoversConcept", ch),
    rlm_ws.Edge("IncludesProblem", ph),
], label="Binary Search")
lh = ws.put_frame(lesson)

# Set a ref (the only mutable state)
ws.set_ref("course/structure", lh)

# Query the graph
atoms = ws.collect_atoms(lh, "ConceptDefinition")  # [(Hash, Atom), ...]
ws.reverse_edges(ch)                                # who points to this concept?
ws.by_tag("algorithms")                             # tag lookup

# Reopen later — everything persists
ws2 = rlm_ws.Workspace.open("/tmp/my-course")
assert ws2.get_ref_hash("course/structure") == lh
```

### Rust only

```bash
cd rlm-ws
cargo test           # 69 tests
cargo clippy --all-targets  # zero warnings
```

```rust
use rlm_ws::*;

let ws = Workspace::init(Path::new("/tmp/my-course")).unwrap();

let atom = Atom {
    kind: AtomKind::ConceptDefinition,
    content: AtomContent::text("Binary search is O(log n)"),
    metadata: AtomMetadata::now().with_tags(vec!["algorithms".into()]),
};
let hash = ws.put(&atom).unwrap();
```

## Architecture

```
.rlm/                          ← the workspace (single source of truth)
├── config                     ← workspace metadata (TOML)
├── objects/
│   └── ab/cd1234...           ← content-addressed, sharded by first 2 hex chars
├── refs/
│   ├── HEAD
│   ├── course/structure       ← named mutable pointers (the ONLY mutable state)
│   └── student/alice/mastery
├── index/
│   └── index.sqlite3          ← secondary indexes (derived, rebuildable)
└── tmp/                       ← staging area for atomic writes
```

### Object model

Four primitive types, all immutable and content-addressed (SHA-256):

| Type | Role | Analogy |
|---|---|---|
| **Atom** | Leaf content (concept definitions, problems, model outputs, student responses) | Git blob |
| **Frame** | Typed edges to other objects (lessons, modules, student models) | Git tree |
| **Event** | Temporal record of something that happened (model calls, mastery updates) | Git commit |
| **Ref** | Named mutable pointer to a hash | Git ref |

Objects are never mutated. A new version of anything is a new object with a new hash. Refs are the only mutable state.

### Plumbing / porcelain split

The Rust core is deliberately boring: object serialization, hashing, storage, refs, graph traversal, and rebuildable indexes. It contains no ML models, no retrieval policies, no pedagogy.

The Python layer (to be built on top of this crate) handles retrieval strategies, execution orchestration, model-provider adapters, and tutoring logic. This separation keeps the storage engine deterministic and inspectable without network access.

### Key invariants

- **`put` never requires network access.** Embeddings are derived, optional, and out-of-band.
- **Derived data is never required for correctness.** The SQLite index can be deleted and rebuilt from the object store with `ws.rebuild_index()`.
- **Concurrent safety via CAS.** Compare-and-swap on refs is the only synchronization primitive. Objects are append-only and idempotent.
- **Course content is shared, student state is per-student.** Course refs under `course/` are effectively read-only during tutoring. Student state lives under `student/{id}/`.

## Development

### Prerequisites

- **Rust** ≥ 1.83 (via [rustup](https://rustup.rs/))
- **Python** ≥ 3.9
- **uv** (`pip install uv` or see [docs](https://docs.astral.sh/uv/))

### Setup

```bash
# Clone and enter the project
git clone <repo> && cd rlm-ws

# Rust: check, lint, test (no Python needed — pybridge is feature-gated)
cargo clippy --all-targets   # must be zero warnings (deny(warnings) is set)
cargo test                   # 69 tests: 66 unit + 3 integration

# Python: venv, build, test (maturin activates the "python" feature automatically)
uv sync
uv pip install maturin
uv run maturin develop          # builds Rust + pybridge → installs as Python native module
uv run python tests/test_python.py  # 12 tests
```

### Project layout

```
src/
├── lib.rs          ← crate root, lint policy, re-exports
├── error.rs        ← error types (thiserror)
├── hash.rs         ← SHA-256 content hash with serde for bincode + JSON
├── types.rs        ← Atom, Frame, Event, all enums, json_value_compat
├── envelope.rs     ← on-disk binary format, Storable trait
├── store.rs        ← content-addressable filesystem store
├── refs.rs         ← mutable named pointers, CAS
├── graph.rs        ← BFS/DFS traversal, call trees, shortest path
├── index.rs        ← SQLite secondary indexes (derived, rebuildable)
├── workspace.rs    ← top-level API, commit_mutation, GC, export
└── pybridge.rs     ← PyO3 bindings (all types + Workspace)

tests/
├── integration.rs  ← full tutoring session lifecycle (Rust)
└── test_python.py  ← Python bridge tests
```

### Lint policy

The crate uses `#![deny(warnings)]` and `#![deny(clippy::all)]` with `#![warn(clippy::pedantic)]`. All code must compile with zero warnings. A few pedantic lints are explicitly allowed where they conflict with library ergonomics (documented in `lib.rs`).

### Serialization: known constraints

Two implementation constraints discovered during development, worth knowing before modifying types:

1. **`skip_serializing_if` is incompatible with bincode.** Bincode is a positional format. Skipping a field during serialization shifts all subsequent byte offsets, causing deserialization failures. Never use `#[serde(skip_serializing_if = "...")]` on any type that goes through bincode (which is all `Storable` types).

2. **`serde_json::Value` requires a compatibility wrapper for bincode.** Bincode doesn't support `deserialize_any`, which `serde_json::Value` requires. The `json_value_compat` module in `types.rs` serializes JSON values as strings in binary formats and as native JSON in human-readable formats. All `Option<serde_json::Value>` fields must use `#[serde(default, with = "json_value_compat")]`.

### Dependency notes

| Crate | Version | Why this version |
|---|---|---|
| `sha2` | `0.10` | Current stable RustCrypto generation. Semver-stable, no upper bound needed. |
| `serde` | `1` | API-stable for years. The entire Rust ecosystem depends on serde 1.x. |
| `serde_json` | `1` | Same stability story as serde. |
| `bincode` | `1` | Pinned to 1.x deliberately. Bincode 2.0 is a complete rewrite that drops serde in favor of its own `Encode`/`Decode` traits. Our `Storable` trait and `json_value_compat` module depend on bincode 1's serde integration. Migration to bincode 2 would be a deliberate, breaking change to the on-disk format. |
| `chrono` | `0.4` | Standard datetime library. `default-features = false` avoids the deprecated `oldtime` feature. Only `std`, `clock`, and `serde` are needed. |
| `thiserror` | `2` | Error derive macros. 2.x is the current generation for Rust >= 1.83. |
| `tempfile` | `3` | Atomic file operations for the tmp-then-rename write pattern. Also used in tests. |
| `rusqlite` | `0.38` | SQLite bindings. `bundled` feature compiles SQLite from source to eliminate system dependency. Adds ~30s to clean builds but works everywhere without `apt install libsqlite3-dev`. |
| `pyo3` | `0.28` | Python bindings. Uses the Bound API introduced in 0.22+. Requires Rust >= 1.83. |

### The three-step mutation pattern

State changes follow a specific protocol (from spec section 14.3):

```python
# 1. Write immutable objects
new_model = ws.put_frame(Frame("StudentModel", [...]))

# 2. Record an Event
event = Event("StudentModelUpdate",
    inputs=[EventRef(old_model, "prior")],
    outputs=[EventRef(new_model, "updated")])

# 3. CAS the ref
ws.commit_mutation(event, [
    ("student/alice/mastery", old_model, new_model),
])
```

`commit_mutation` performs steps 2 and 3 atomically. If the CAS fails (ref was updated by another process), the event is still written (harmless — objects are immutable) but the ref is not updated, and a `ValueError` is raised.

## License

TBD
