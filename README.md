# RLM Workspace Specification

**Project Codename:** `rlm-ws`
**Version:** 0.1.0-draft
**Date:** 2026-03-21

---

## 1. Overview

### 1.1 What This Is

`rlm-ws` is a content-addressable object store and runtime for Recursive Language Model (RLM) architectures, designed to serve as the persistent foundation for an AI tutoring system. It is analogous to Git's object model, but adapted for the domain of knowledge representation, pedagogical state tracking, and recursive LLM orchestration.

The system manages four primitive object types — Atoms, Frames, Events, and Refs — stored immutably in a content-addressable store (SHA-256 indexed). All higher-level operations (retrieval, scoped execution, observability, state evolution) emerge from traversal and manipulation of these primitives.

### 1.2 Design Principles

1. **Content-addressable immutability.** Objects are never mutated. A new version of anything is a new object with a new hash. The only mutable state in the entire system is Refs (named pointers).
2. **The workspace IS the application.** Intelligence lives in the structured artifact graph on disk, not in any orchestration layer. The TUI, the model adapter, the retrieval engine — these are all views and operators over the workspace.
3. **Minimal primitives, emergent operations.** The object model is deliberately small. Scoped views, versioning, retrieval, execution traces, and merge semantics all emerge from the four object types and their relationships.
4. **Rust core, Python surface.** The object store, hashing, serialization, graph traversal, and index management are implemented in Rust for correctness and performance. The retrieval policies, model call orchestration, and tutoring logic live in Python, importing the Rust core via PyO3.

### 1.3 Architectural Context

```
┌─────────────────────────────────────────────────┐
│              Python Orchestration                │
│  ┌──────────┐ ┌──────────────┐ ┌─────────────┐  │
│  │ Retrieval│ │  Execution   │ │   Tutoring   │  │
│  │ Policies │ │    Engine    │ │    Logic     │  │
│  └────┬─────┘ └──────┬───────┘ └──────┬──────┘  │
│       │              │                │          │
│       ▼              ▼                ▼          │
│  ┌──────────────────────────────────────────┐    │
│  │         Python ↔ Rust Bridge (PyO3)      │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│                 Rust Core (rlm-ws)               │
│  ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │
│  │  Object  │ │   Graph  │ │    Secondary     │  │
│  │  Store   │ │ Traversal│ │     Indexes      │  │
│  └────┬─────┘ └──────────┘ └─────────────────┘  │
│       │                                          │
│  ┌────▼──────────────────────────────────────┐   │
│  │          .rlm/ Directory (on disk)        │   │
│  │  objects/  refs/  index/  config           │   │
│  └───────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

### 1.4 Relationship to RLM Paper

The RLM paper (Recursive Language Models) describes an architecture where a root LM call can spawn child LM calls, each operating over a subset of an environment, with results composed back up the call tree. This project implements the **environment** that such calls operate over. Specifically:

- **Persistent state** → the object store (Atoms, Frames, Refs)
- **Scoped sub-calls** → scoped views constructed from subsets of the artifact graph
- **Context-aware retrieval** → parameterized graph queries over typed edges and indexes
- **Execution traces** → Events as first-class objects, forming a queryable DAG
- **Bidirectional control flow** → the Python execution engine mediating between model outputs and store operations

---

## 2. On-Disk Layout

The workspace lives in a `.rlm/` directory at the root of a course or project. This directory is the single source of truth.

```
.rlm/
├── config                      # Workspace configuration (TOML)
├── objects/
│   ├── ab/
│   │   └── cd1234...           # Object files, sharded by first 2 hex chars
│   ├── ef/
│   │   └── 5678ab...
│   └── ...
├── refs/
│   ├── HEAD                    # Current workspace state (points to latest root Frame)
│   ├── student/
│   │   └── mastery             # Latest student model Frame
│   ├── course/
│   │   └── structure           # Canonical course graph Frame
│   └── session/
│       └── current             # Current active session Event chain
├── index/
│   └── index.sqlite3           # Secondary indexes (concept lookup, temporal, embeddings)
└── tmp/                        # Temporary staging area for atomic writes
```

### 2.1 Config

```toml
[workspace]
version = 1
created_at = "2026-03-21T00:00:00Z"

[hashing]
algorithm = "sha256"

[serialization]
format = "bincode"              # Internal object format
human_readable_format = "json"  # For export/inspection

[compression]
algorithm = "zstd"
level = 3

[index]
backend = "sqlite"
embedding_dimensions = 384      # For optional embedding index
```

---

## 3. Object Model

All objects are immutable. Once written, an object's content never changes. Its identity IS its content hash. Four primitive types exist.

### 3.1 Common Object Envelope

Every object on disk has this structure:

```
┌──────────────────────────────┐
│  Magic bytes: "RLMW"  (4B)  │
│  Version: u8           (1B)  │
│  Object type: u8       (1B)  │
│  Compression flag: u8  (1B)  │
│  Reserved: u8          (1B)  │
│  Content length: u64   (8B)  │
│  Content: [u8]         (var) │
└──────────────────────────────┘
```

Object type codes:
- `0x01` — Atom
- `0x02` — Frame
- `0x03` — Event
- `0xFF` — Reserved

The content is the serialized (and optionally compressed) object body. The hash is computed over the **uncompressed serialized body only** (not the envelope), ensuring the same logical content always produces the same hash regardless of compression settings.

### 3.2 Hash

```rust
pub struct Hash([u8; 32]); // SHA-256

impl Hash {
    /// Compute hash from raw serialized bytes (pre-compression).
    pub fn compute(data: &[u8]) -> Hash;

    /// Hex-encoded string representation.
    pub fn to_hex(&self) -> String;

    /// Shard prefix for filesystem storage (first 2 hex chars).
    pub fn shard_prefix(&self) -> String;
}
```

Display format: full 64-character lowercase hex string. Short display (for logs, UI): first 8 hex characters.

### 3.3 Atom

An Atom is the smallest unit of content. It is a blob with a declared kind. Atoms are leaf nodes — they reference no other objects.

```rust
pub struct Atom {
    pub kind: AtomKind,
    pub content: AtomContent,
    pub metadata: AtomMetadata,
}

pub enum AtomKind {
    /// A concept definition: a single teachable idea.
    ConceptDefinition,
    /// A lesson body: prose explanation of one or more concepts.
    LessonBody,
    /// A problem statement: an exercise, quiz question, or challenge.
    ProblemStatement,
    /// A worked example: a step-by-step solution to a problem.
    WorkedExample,
    /// A student response: verbatim text of what the student produced.
    StudentResponse,
    /// A model output: verbatim text of what the LLM produced.
    ModelOutput,
    /// An annotation: a judgment, feedback, or note attached to other content.
    Annotation,
    /// A configuration blob: system prompt fragment, retrieval policy config, etc.
    Config,
    /// Freeform content that doesn't fit other categories.
    Blob,
}

pub struct AtomContent {
    /// Primary content, typically text. For non-text content, this may be
    /// a description or empty, with the payload in `binary`.
    pub text: String,
    /// Optional structured data (JSON-compatible).
    pub structured: Option<serde_json::Value>,
    /// Optional binary payload (e.g., an image, audio clip).
    /// Stored as the raw bytes. The hash covers these bytes.
    pub binary: Option<Vec<u8>>,
    /// MIME type for binary content, if present.
    pub mime_type: Option<String>,
}

pub struct AtomMetadata {
    /// When this atom was created (wall-clock time).
    pub created_at: DateTime<Utc>,
    /// Freeform tags for lightweight categorization.
    pub tags: Vec<String>,
    /// Optional embedding vector for semantic search.
    /// NOT included in hash computation (derived data).
    #[serde(skip)]
    pub embedding: Option<Vec<f32>>,
}
```

**Hash computation for Atoms:** The hash is computed over the serialized `(kind, content)` tuple. Metadata fields like `created_at` and `tags` ARE included in the hash (they are part of the atom's identity). The `embedding` field is NOT included (it is derived, stored only in the index).

**Design rationale — why Atoms have kinds:** The kind field enables typed retrieval without inspecting content. "Give me all ProblemStatements related to concept X" is a graph query that never needs to parse text. The kind is part of the hash, so the same text as a ConceptDefinition vs. a LessonBody produces different atoms. This is intentional — they are semantically different objects.

### 3.4 Frame

A Frame is a structured collection of typed, directed edges pointing to other objects (Atoms or other Frames). Frames are the graph-building primitive. They define relationships.

```rust
pub struct Frame {
    pub kind: FrameKind,
    pub edges: Vec<Edge>,
    pub metadata: FrameMetadata,
}

pub enum FrameKind {
    /// A lesson: groups concept definitions, problems, examples into a teachable unit.
    Lesson,
    /// A module: groups lessons into a larger curricular unit.
    Module,
    /// A course: the top-level curricular structure.
    Course,
    /// A student model: represents the system's belief about student knowledge state.
    StudentModel,
    /// A session snapshot: captures the state of a tutoring session at a point in time.
    SessionSnapshot,
    /// A retrieval scope: defines a subset of the graph for a scoped sub-call.
    RetrievalScope,
    /// A call context: bundles everything needed for a single LLM invocation.
    CallContext,
    /// Generic grouping.
    Collection,
}

pub struct Edge {
    pub label: EdgeLabel,
    pub target: Hash,
    /// Optional scalar annotation on the edge (e.g., mastery level, relevance score).
    pub weight: Option<f64>,
    /// Optional structured annotation on the edge.
    pub annotation: Option<serde_json::Value>,
}

pub enum EdgeLabel {
    // --- Curricular structure ---
    /// This frame/atom is a prerequisite for understanding the parent.
    Prerequisite,
    /// The parent frame covers/teaches this concept atom.
    CoversConcept,
    /// The parent frame contains this sub-frame (lesson in module, module in course).
    Contains,
    /// The parent frame includes this problem/example atom.
    IncludesProblem,
    IncludesExample,

    // --- Student model ---
    /// Edge from StudentModel frame to a concept atom. Weight = mastery level [0.0, 1.0].
    MasteryEstimate,
    /// Edge from StudentModel to an atom recording a misconception.
    Misconception,
    /// Edge from StudentModel to a session event where the student interacted with this concept.
    InteractionRecord,

    // --- Session and execution ---
    /// Points to an atom containing the model's output for this context.
    ProducedOutput,
    /// Points to an atom containing the student's response.
    ReceivedInput,
    /// Points to the retrieval scope frame used for a sub-call.
    UsedScope,
    /// Points to a child call context frame (recursive sub-call).
    SpawnedChild,

    // --- Retrieval and scoping ---
    /// Generic "includes this object in scope" edge.
    InScope,
    /// Edge to the retrieval policy config atom.
    RetrievalPolicy,

    // --- Generic ---
    /// A relationship that doesn't fit the above. The annotation field should describe it.
    Custom,
}

pub struct FrameMetadata {
    pub created_at: DateTime<Utc>,
    pub tags: Vec<String>,
    /// Human-readable label for display (not part of identity if `label_in_hash` is false).
    pub label: Option<String>,
    /// Whether the label is semantically meaningful (true) or just display sugar (false).
    /// If true, the label is included in hash computation.
    pub label_in_hash: bool,
}
```

**Hash computation for Frames:** Computed over `(kind, edges_sorted_by_target_hash, label?)`. Edges are sorted by target hash to ensure deterministic ordering. If `label_in_hash` is true, the label is included. Metadata timestamps and tags ARE included.

**Design rationale — why Frames have kinds:** Same reasoning as Atom kinds. A StudentModel frame and a Lesson frame have fundamentally different semantics even if they happen to have similar edge structures. The kind enables type-safe operations: "update mastery estimates" only operates on StudentModel frames; "list prerequisites" only makes sense on Lesson/Module frames.

**Design rationale — why edges have weights and annotations:** The mastery estimate on a MasteryEstimate edge is `weight: Some(0.73)`. A misconception edge might have `annotation: Some({"description": "confuses recursion base case with inductive step"})`. This avoids creating a separate Atom for every scalar annotation, keeping the graph lean.

### 3.5 Event

An Event records that something happened. Events are the temporal backbone of the system. They form a DAG (not a linear chain) because concurrent or branching activities are possible.

```rust
pub struct Event {
    pub kind: EventKind,
    /// Parent events (zero or more). Zero parents = root event (e.g., session start).
    /// Multiple parents = merge event (e.g., session that incorporates multiple sub-call results).
    pub parents: Vec<Hash>,
    /// Objects that were READ as inputs to whatever produced this event.
    pub inputs: Vec<EventRef>,
    /// Objects that were CREATED as outputs of whatever produced this event.
    pub outputs: Vec<EventRef>,
    /// The trace of the operation that produced this event.
    pub trace: CallTrace,
    pub metadata: EventMetadata,
}

pub struct EventRef {
    /// The hash of the referenced object.
    pub hash: Hash,
    /// Why this object was an input/output.
    pub role: String,
}

pub enum EventKind {
    /// A tutoring session started.
    SessionStart,
    /// A tutoring session ended.
    SessionEnd,
    /// An LLM call was made (root or sub-call).
    ModelCall,
    /// The student provided input.
    StudentInput,
    /// The system updated the student model.
    StudentModelUpdate,
    /// A retrieval operation was performed.
    RetrievalPerformed,
    /// A merge of sub-call results occurred.
    Merge,
    /// An administrative event (workspace init, config change, manual edit).
    Admin,
}

pub struct CallTrace {
    /// Which model was called (e.g., "claude-sonnet-4-20250514", "gpt-4o").
    pub model: Option<String>,
    /// The system prompt or prompt template identifier used.
    pub prompt_template: Option<String>,
    /// Token counts.
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    /// Latency in milliseconds.
    pub latency_ms: Option<u64>,
    /// The retrieval scope frame hash, if retrieval was involved.
    pub retrieval_scope: Option<Hash>,
    /// Depth in the recursive call tree (0 = root).
    pub call_depth: u32,
    /// Parent call event hash, if this is a sub-call.
    pub parent_call: Option<Hash>,
    /// Arbitrary metadata for debugging/analysis.
    pub extra: Option<serde_json::Value>,
}

pub struct EventMetadata {
    pub timestamp: DateTime<Utc>,
    pub tags: Vec<String>,
}
```

**Hash computation for Events:** Computed over `(kind, parents, inputs, outputs, trace)`. Timestamps ARE included (two events at different times with identical content are different events).

**Design rationale — Events vs. git commits:** Git commits represent snapshots of the entire tree. Events are more granular — they record individual operations with explicit input/output provenance. This enables queries like "show me every model call that read concept X and produced a mastery update" which would be very difficult with commit-level granularity.

### 3.6 Ref

Refs are the only mutable state. A Ref is a named pointer to a Hash. They are stored as plain files: the file path is the ref name, the file content is the hex-encoded hash.

```
refs/HEAD                       → abc123...   (hash of current root Frame)
refs/student/mastery            → def456...   (hash of latest StudentModel Frame)
refs/course/structure           → 789abc...   (hash of Course Frame)
refs/session/current            → fedcba...   (hash of latest Event)
refs/session/2026-03-21-001     → 112233...   (hash of a specific session's root Event)
```

```rust
pub struct Ref {
    pub name: String,       // e.g., "student/mastery"
    pub target: Hash,
}

/// Ref operations are atomic (write to tmp, rename).
impl RefStore {
    pub fn read(&self, name: &str) -> Result<Hash>;
    pub fn write(&self, name: &str, target: Hash) -> Result<()>;
    pub fn delete(&self, name: &str) -> Result<()>;
    pub fn list(&self, prefix: &str) -> Result<Vec<Ref>>;

    /// Compare-and-swap: only update if current value matches `expected`.
    /// Returns Err if the ref has been updated by another process.
    pub fn cas(&self, name: &str, expected: Hash, new: Hash) -> Result<()>;
}
```

**Atomicity:** Ref writes use the tmp-file-then-rename pattern (same as Git) to ensure atomicity. The `cas` method enables safe concurrent updates.

---

## 4. Rust Core API

### 4.1 Object Store

The object store is the lowest-level component. It stores and retrieves raw objects by hash.

```rust
pub struct ObjectStore {
    root: PathBuf,  // path to .rlm/objects/
}

impl ObjectStore {
    /// Open or create an object store at the given .rlm/ root.
    pub fn open(rlm_root: &Path) -> Result<Self>;

    /// Write an object. Returns the hash.
    /// If the object already exists (same hash), this is a no-op.
    pub fn write<T: Storable>(&self, obj: &T) -> Result<Hash>;

    /// Read an object by hash. Returns None if not found.
    pub fn read<T: Storable>(&self, hash: &Hash) -> Result<Option<T>>;

    /// Check if an object exists without reading it.
    pub fn exists(&self, hash: &Hash) -> bool;

    /// Read the raw object envelope (for inspection/debugging).
    pub fn read_raw(&self, hash: &Hash) -> Result<Option<ObjectEnvelope>>;

    /// Iterate all objects of a given type.
    pub fn iter_type(&self, type_code: u8) -> impl Iterator<Item = (Hash, ObjectEnvelope)>;

    /// Garbage collection: remove objects not reachable from any ref.
    /// Returns the set of removed hashes.
    pub fn gc(&self, refs: &RefStore) -> Result<HashSet<Hash>>;
}

/// Trait for types that can be stored in the object store.
pub trait Storable: Serialize + DeserializeOwned {
    const TYPE_CODE: u8;
    /// Serialize to bytes for hashing and storage.
    fn to_bytes(&self) -> Result<Vec<u8>>;
    /// Deserialize from bytes.
    fn from_bytes(data: &[u8]) -> Result<Self>;
}
```

**Write path:** serialize → hash raw bytes → check if exists → compress → write envelope to `tmp/` → rename to `objects/{shard}/{hash}`.

**Read path:** compute shard from hash → read envelope → decompress → deserialize.

### 4.2 Graph Traversal

```rust
pub struct Graph {
    store: ObjectStore,
}

impl Graph {
    /// Walk all objects reachable from a starting hash, following edges in Frames
    /// and parent/input/output links in Events.
    pub fn walk(&self, start: &Hash, direction: Direction) -> GraphWalker;

    /// Find all Frames that contain an edge pointing to the given target hash.
    /// Requires the reverse-edge index.
    pub fn reverse_edges(&self, target: &Hash) -> Result<Vec<(Hash, Edge)>>;

    /// Find all paths between two objects, up to a maximum depth.
    pub fn paths_between(
        &self,
        from: &Hash,
        to: &Hash,
        max_depth: usize,
    ) -> Result<Vec<Vec<Hash>>>;

    /// Collect all Atoms reachable from a Frame, optionally filtered by AtomKind.
    pub fn collect_atoms(
        &self,
        frame: &Hash,
        kind_filter: Option<&[AtomKind]>,
    ) -> Result<Vec<(Hash, Atom)>>;

    /// Collect all Events in a session (following parent links back to SessionStart).
    pub fn session_events(&self, session_ref: &Hash) -> Result<Vec<(Hash, Event)>>;

    /// Build the recursive call tree from a root ModelCall event.
    pub fn call_tree(&self, root_event: &Hash) -> Result<CallTreeNode>;
}

pub struct CallTreeNode {
    pub event_hash: Hash,
    pub event: Event,
    pub children: Vec<CallTreeNode>,
}

pub enum Direction {
    /// Follow edges/links forward (from parent to child).
    Forward,
    /// Follow edges/links backward (from child to parent). Requires reverse index.
    Reverse,
    /// Follow in both directions.
    Both,
}
```

### 4.3 Secondary Indexes

The secondary indexes live in SQLite. They are **derived data** — they can always be rebuilt from the object store. They exist purely for query performance.

```rust
pub struct Index {
    db: rusqlite::Connection,  // .rlm/index/index.sqlite3
}

impl Index {
    pub fn open(rlm_root: &Path) -> Result<Self>;

    /// Rebuild the entire index from the object store. Idempotent.
    pub fn rebuild(&self, store: &ObjectStore) -> Result<()>;

    /// Index a newly written object (incremental update).
    pub fn index_object(&self, hash: &Hash, obj: &dyn Storable) -> Result<()>;

    // --- Concept index ---
    /// Find all objects related to a concept (by concept atom hash).
    pub fn by_concept(&self, concept_hash: &Hash) -> Result<Vec<Hash>>;

    // --- Kind index ---
    /// Find all Atoms of a given kind.
    pub fn atoms_by_kind(&self, kind: AtomKind) -> Result<Vec<Hash>>;
    /// Find all Frames of a given kind.
    pub fn frames_by_kind(&self, kind: FrameKind) -> Result<Vec<Hash>>;
    /// Find all Events of a given kind.
    pub fn events_by_kind(&self, kind: EventKind) -> Result<Vec<Hash>>;

    // --- Temporal index ---
    /// Find Events in a time range, ordered by timestamp.
    pub fn events_in_range(
        &self,
        after: DateTime<Utc>,
        before: DateTime<Utc>,
    ) -> Result<Vec<Hash>>;
    /// Find the N most recent Events, optionally filtered by kind.
    pub fn recent_events(
        &self,
        n: usize,
        kind: Option<EventKind>,
    ) -> Result<Vec<Hash>>;

    // --- Tag index ---
    /// Find all objects with a given tag.
    pub fn by_tag(&self, tag: &str) -> Result<Vec<Hash>>;

    // --- Reverse edge index ---
    /// Find all Frames that have an edge pointing to the given hash.
    pub fn reverse_edges(&self, target: &Hash) -> Result<Vec<(Hash, EdgeLabel)>>;

    // --- Embedding index (optional) ---
    /// Find the K nearest neighbors to a query vector.
    pub fn nearest_neighbors(
        &self,
        query: &[f32],
        k: usize,
        kind_filter: Option<AtomKind>,
    ) -> Result<Vec<(Hash, f32)>>;  // (hash, distance)

    /// Store an embedding for an atom.
    pub fn store_embedding(&self, hash: &Hash, embedding: &[f32]) -> Result<()>;
}
```

**SQLite schema (conceptual):**

```sql
-- Object metadata (all types)
CREATE TABLE objects (
    hash        BLOB PRIMARY KEY,
    type_code   INTEGER NOT NULL,
    kind        TEXT NOT NULL,       -- e.g., "ConceptDefinition", "Lesson", "ModelCall"
    created_at  TEXT NOT NULL,       -- ISO 8601
    label       TEXT                 -- human-readable, nullable
);

-- Tags (many-to-many)
CREATE TABLE tags (
    hash    BLOB NOT NULL,
    tag     TEXT NOT NULL,
    PRIMARY KEY (hash, tag)
);
CREATE INDEX idx_tags_tag ON tags(tag);

-- Edges (denormalized from Frames for fast reverse lookup)
CREATE TABLE edges (
    source_hash BLOB NOT NULL,      -- the Frame containing this edge
    target_hash BLOB NOT NULL,      -- the edge target
    label       TEXT NOT NULL,       -- EdgeLabel variant name
    weight      REAL,
    PRIMARY KEY (source_hash, target_hash, label)
);
CREATE INDEX idx_edges_target ON edges(target_hash, label);

-- Events (temporal index)
CREATE TABLE events (
    hash        BLOB PRIMARY KEY,
    kind        TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    call_depth  INTEGER,
    parent_call BLOB                -- parent ModelCall event, for call tree queries
);
CREATE INDEX idx_events_time ON events(timestamp);
CREATE INDEX idx_events_kind ON events(kind, timestamp);

-- Embeddings (optional, for semantic search)
-- Using a simple brute-force approach initially.
-- Can be swapped for sqlite-vss or similar later.
CREATE TABLE embeddings (
    hash        BLOB PRIMARY KEY,
    vector      BLOB NOT NULL       -- f32 array, serialized
);
```

### 4.4 Workspace

The top-level Rust API that ties everything together.

```rust
pub struct Workspace {
    pub store: ObjectStore,
    pub refs: RefStore,
    pub graph: Graph,
    pub index: Index,
    root: PathBuf,
}

impl Workspace {
    /// Initialize a new workspace at the given path.
    /// Creates the .rlm/ directory and all subdirectories.
    pub fn init(path: &Path) -> Result<Self>;

    /// Open an existing workspace.
    pub fn open(path: &Path) -> Result<Self>;

    /// Write an object and update indexes. Returns the hash.
    pub fn put<T: Storable>(&self, obj: &T) -> Result<Hash>;

    /// Read an object by hash.
    pub fn get<T: Storable>(&self, hash: &Hash) -> Result<Option<T>>;

    /// Resolve a ref name to a hash, then read the object.
    pub fn get_ref<T: Storable>(&self, ref_name: &str) -> Result<Option<T>>;

    /// Update a ref to point to a new hash.
    pub fn set_ref(&self, ref_name: &str, hash: &Hash) -> Result<()>;

    /// Create a ScopedView: a restricted, read-only projection of the workspace.
    pub fn scoped_view(&self, roots: &[Hash]) -> Result<ScopedView>;

    /// Run garbage collection.
    pub fn gc(&self) -> Result<GcReport>;

    /// Export the workspace (or a subtree) as human-readable JSON.
    pub fn export_json(&self, root: &Hash, writer: &mut dyn Write) -> Result<()>;

    /// Import objects from a JSON export.
    pub fn import_json(&self, reader: &mut dyn Read) -> Result<Vec<Hash>>;
}
```

---

## 5. Scoped Views

A ScopedView is the mechanism for scope isolation in recursive sub-calls. It is a read-only projection of the workspace rooted at a specific set of objects.

```rust
pub struct ScopedView {
    /// The workspace this view is derived from.
    workspace: Arc<Workspace>,
    /// Root objects defining the scope boundary.
    roots: Vec<Hash>,
    /// Lazily computed set of all hashes reachable from roots.
    reachable: OnceCell<HashSet<Hash>>,
}

impl ScopedView {
    /// Read an object, but only if it's within scope.
    pub fn get<T: Storable>(&self, hash: &Hash) -> Result<Option<T>>;

    /// Check if a hash is within this scope.
    pub fn contains(&self, hash: &Hash) -> bool;

    /// Iterate all atoms in scope, optionally filtered by kind.
    pub fn atoms(&self, kind: Option<AtomKind>) -> Result<Vec<(Hash, Atom)>>;

    /// Iterate all frames in scope, optionally filtered by kind.
    pub fn frames(&self, kind: Option<FrameKind>) -> Result<Vec<(Hash, Frame)>>;

    /// Graph traversal within scope bounds.
    pub fn walk(&self, start: &Hash) -> ScopedWalker;

    /// Create a sub-scope (further restriction of this scope).
    pub fn narrow(&self, roots: &[Hash]) -> Result<ScopedView>;
}
```

**How sub-calls use ScopedViews:**

1. The parent call determines what a child call needs to see (e.g., "the concept definition for binary search, the student's last 3 interactions with it, and the relevant problem set").
2. It constructs a `RetrievalScope` Frame with `InScope` edges pointing to those objects.
3. It writes that Frame and creates a `ScopedView` from it.
4. The child call receives this ScopedView. It can read anything reachable from the scope roots but nothing outside.
5. The child call creates new objects (Atoms, Frames, Events) in the main store (writes are not scoped — new objects are always globally visible).
6. The child call returns the hashes of its outputs.
7. The parent inspects the outputs, decides what to incorporate, and updates its own Frames/Refs accordingly.

---

## 6. Retrieval System

Retrieval is the interface through which the LLM accesses the artifact graph. It lives in Python but uses the Rust core for all store/graph operations.

### 6.1 Retrieval Query

```python
@dataclass
class RetrievalQuery:
    """A parameterized retrieval request."""

    # What kind of content to retrieve.
    target_kinds: list[AtomKind | FrameKind] = field(default_factory=list)

    # Concepts to focus on (hashes of ConceptDefinition atoms).
    focus_concepts: list[Hash] = field(default_factory=list)

    # The intent of the retrieval (used to select/weight strategies).
    intent: RetrievalIntent = RetrievalIntent.GENERAL

    # Temporal weighting: higher = more recent content preferred.
    recency_weight: float = 0.5

    # Maximum number of results.
    max_results: int = 20

    # If provided, only retrieve within this scope.
    scope: ScopedView | None = None

    # If provided, use this student model for mastery-aware filtering.
    student_model: Hash | None = None

    # Optional free-text query for semantic similarity.
    text_query: str | None = None


class RetrievalIntent(Enum):
    """Why the model is retrieving — determines strategy weighting."""
    GENERAL = "general"
    EXPLAIN_CONCEPT = "explain_concept"
    GENERATE_PROBLEM = "generate_problem"
    DIAGNOSE_MISCONCEPTION = "diagnose_misconception"
    ASSESS_MASTERY = "assess_mastery"
    PLAN_LESSON = "plan_lesson"
    REVIEW_SESSION_HISTORY = "review_session_history"
```

### 6.2 Retrieval Strategies

Retrieval is not a single function. It is a **pipeline of composable strategies**, each producing a scored candidate set, which are then merged and ranked.

```python
class RetrievalStrategy(Protocol):
    """A single retrieval strategy that produces scored candidates."""

    def retrieve(
        self,
        query: RetrievalQuery,
        workspace: Workspace,
    ) -> list[ScoredCandidate]:
        ...


@dataclass
class ScoredCandidate:
    hash: Hash
    score: float           # [0.0, 1.0]
    source_strategy: str   # which strategy produced this candidate
    explanation: str       # why this candidate was selected (for observability)
```

**Built-in strategies:**

| Strategy | What it does | When it's weighted highly |
|---|---|---|
| `GraphProximity` | BFS/DFS from focus concepts, scoring by edge distance. | Always, as baseline. |
| `MasteryAware` | Filters/boosts based on student model. Low-mastery concepts boosted, high-mastery deprioritized. | `DIAGNOSE_MISCONCEPTION`, `ASSESS_MASTERY` |
| `TemporalRecency` | Scores by timestamp. Recent events and their associated objects score higher. | `REVIEW_SESSION_HISTORY`, high `recency_weight` |
| `SemanticSimilarity` | Embedding-based nearest-neighbor search using `text_query`. | When `text_query` is provided. |
| `PrerequisiteChain` | Follows Prerequisite edges to find foundational content. | `EXPLAIN_CONCEPT`, `PLAN_LESSON` |
| `InteractionHistory` | Finds objects the student has previously interacted with (via Events). | `DIAGNOSE_MISCONCEPTION`, `ASSESS_MASTERY` |

### 6.3 Retrieval Policy

A RetrievalPolicy defines how strategies are composed for a given intent.

```python
@dataclass
class RetrievalPolicy:
    """Defines how strategies are weighted and composed for a given intent."""

    strategies: list[tuple[RetrievalStrategy, float]]  # (strategy, weight)

    def execute(
        self,
        query: RetrievalQuery,
        workspace: Workspace,
    ) -> list[ScoredCandidate]:
        """Run all strategies, merge candidates, return ranked results."""
        all_candidates: dict[Hash, ScoredCandidate] = {}
        for strategy, weight in self.strategies:
            candidates = strategy.retrieve(query, workspace)
            for c in candidates:
                if c.hash in all_candidates:
                    # Merge: keep highest weighted score, accumulate explanations.
                    existing = all_candidates[c.hash]
                    existing.score = max(existing.score, c.score * weight)
                    existing.explanation += f" | {c.explanation}"
                else:
                    c.score *= weight
                    all_candidates[c.hash] = c
        ranked = sorted(all_candidates.values(), key=lambda c: c.score, reverse=True)
        return ranked[:query.max_results]


# Default policies per intent
DEFAULT_POLICIES: dict[RetrievalIntent, RetrievalPolicy] = {
    RetrievalIntent.EXPLAIN_CONCEPT: RetrievalPolicy(strategies=[
        (GraphProximity(), 0.8),
        (PrerequisiteChain(), 0.9),
        (MasteryAware(), 0.6),
        (SemanticSimilarity(), 0.3),
    ]),
    RetrievalIntent.DIAGNOSE_MISCONCEPTION: RetrievalPolicy(strategies=[
        (InteractionHistory(), 0.9),
        (MasteryAware(), 0.8),
        (GraphProximity(), 0.5),
    ]),
    # ... etc
}
```

---

## 7. Execution Engine

The execution engine lives in Python. It orchestrates recursive LLM calls, manages scoped views, and records Events.

### 7.1 Call Context Construction

Before each LLM invocation, the engine constructs a CallContext Frame containing everything the model needs.

```python
@dataclass
class PreparedCall:
    """Everything needed for a single LLM invocation."""

    # The system prompt (assembled from workspace config + retrieval results).
    system_prompt: str

    # The conversation messages (student input, prior turns in this session).
    messages: list[dict]

    # The retrieval results that informed this call (for provenance).
    retrieved: list[ScoredCandidate]

    # The scoped view for this call (if it's a sub-call).
    scope: ScopedView | None

    # The CallContext frame hash (written to store before the call).
    context_frame_hash: Hash

    # Depth in the call tree.
    depth: int

    # Model to use.
    model: str
```

### 7.2 Execution Loop

```python
class ExecutionEngine:
    def __init__(self, workspace: Workspace, api_client: Any):
        self.workspace = workspace
        self.api = api_client

    async def execute_call(
        self,
        prepared: PreparedCall,
        parent_event: Hash | None = None,
    ) -> ExecutionResult:
        """Execute a single LLM call and record the Event."""

        # 1. Call the model.
        t0 = time.monotonic()
        response = await self.api.create_message(
            model=prepared.model,
            system=prepared.system_prompt,
            messages=prepared.messages,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        # 2. Parse the response for sub-call requests, state mutations, etc.
        parsed = self.parse_response(response)

        # 3. If the model requested sub-calls, execute them recursively.
        child_results = []
        for sub_call_request in parsed.sub_calls:
            child_scope = self.build_child_scope(sub_call_request, prepared.scope)
            child_prepared = self.prepare_call(
                intent=sub_call_request.intent,
                scope=child_scope,
                depth=prepared.depth + 1,
                model=sub_call_request.model or self.select_model(prepared.depth + 1),
            )
            child_result = await self.execute_call(child_prepared, parent_event=None)
            child_results.append(child_result)

        # 4. Write the model output as an Atom.
        output_atom = Atom(
            kind=AtomKind.ModelOutput,
            content=AtomContent(text=response.text),
            metadata=AtomMetadata(created_at=utcnow(), tags=["model-output"]),
        )
        output_hash = self.workspace.put(output_atom)

        # 5. Record the Event.
        event = Event(
            kind=EventKind.ModelCall,
            parents=[parent_event] if parent_event else [],
            inputs=[EventRef(hash=prepared.context_frame_hash, role="call_context")]
                   + [EventRef(hash=c.hash, role="retrieved") for c in prepared.retrieved],
            outputs=[EventRef(hash=output_hash, role="model_output")]
                    + [EventRef(hash=cr.event_hash, role="child_call") for cr in child_results],
            trace=CallTrace(
                model=prepared.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                latency_ms=latency_ms,
                retrieval_scope=prepared.scope.roots[0] if prepared.scope else None,
                call_depth=prepared.depth,
                parent_call=parent_event,
            ),
            metadata=EventMetadata(timestamp=utcnow(), tags=[]),
        )
        event_hash = self.workspace.put(event)

        # 6. Apply state mutations (e.g., mastery updates) if the model requested them.
        mutation_hashes = self.apply_mutations(parsed.mutations)

        return ExecutionResult(
            event_hash=event_hash,
            output_hash=output_hash,
            child_results=child_results,
            mutation_hashes=mutation_hashes,
        )
```

### 7.3 Model Interaction Protocol

The LLM communicates its intentions (sub-calls, state mutations, retrieval requests) through a structured output protocol embedded in the system prompt. The model outputs structured blocks that the execution engine parses.

```python
# The model can emit these structured blocks in its response:

# Request a sub-call:
# <subcall intent="explain_concept" concepts="[hash1, hash2]" model="cheap" />

# Request a mastery update:
# <mastery_update concept="hash1" level="0.73" reason="student demonstrated understanding" />

# Request additional retrieval mid-turn:
# <retrieve intent="diagnose_misconception" concepts="[hash3]" text_query="off by one error" />
```

The execution engine parses these, executes them, and optionally feeds results back into a continuation turn if the model needs the retrieval results to complete its response.

---

## 8. Student Model

The student model is a Frame of kind `StudentModel`. It is the system's belief about what the student knows.

### 8.1 Structure

```
StudentModel Frame
├── MasteryEstimate(weight=0.82) → ConceptDefinition Atom: "Binary Search"
├── MasteryEstimate(weight=0.45) → ConceptDefinition Atom: "Loop Invariants"
├── MasteryEstimate(weight=0.91) → ConceptDefinition Atom: "Array Indexing"
├── Misconception → Annotation Atom: "Confuses base case with inductive step"
│   └── (annotation.concept = hash of "Recursion" concept)
├── InteractionRecord → Event: "Session 2026-03-20, turn 4"
├── InteractionRecord → Event: "Session 2026-03-19, turn 12"
└── ...
```

### 8.2 Update Semantics

Updating the student model means creating a **new** StudentModel Frame with modified edges. The old frame remains in the store (it's immutable). The `student/mastery` ref is updated to point to the new frame.

```python
def update_mastery(
    workspace: Workspace,
    concept_hash: Hash,
    new_level: float,
    reason: str,
    triggering_event: Hash,
) -> Hash:
    """Create a new StudentModel frame with an updated mastery estimate."""
    current_hash = workspace.refs.read("student/mastery")
    current_model: Frame = workspace.get(current_hash)

    # Clone edges, updating the relevant MasteryEstimate.
    new_edges = []
    for edge in current_model.edges:
        if edge.label == EdgeLabel.MasteryEstimate and edge.target == concept_hash:
            new_edges.append(Edge(
                label=EdgeLabel.MasteryEstimate,
                target=concept_hash,
                weight=new_level,
                annotation={"reason": reason, "prior": edge.weight},
            ))
        else:
            new_edges.append(edge)

    # Add an InteractionRecord edge pointing to the triggering event.
    new_edges.append(Edge(
        label=EdgeLabel.InteractionRecord,
        target=triggering_event,
        weight=None,
        annotation=None,
    ))

    new_model = Frame(
        kind=FrameKind.StudentModel,
        edges=new_edges,
        metadata=FrameMetadata(created_at=utcnow(), tags=[], label="student-model"),
    )
    new_hash = workspace.put(new_model)
    workspace.set_ref("student/mastery", new_hash)

    return new_hash
```

Because old StudentModel frames are preserved, the system can examine mastery trajectory over time: "How did the student's understanding of recursion evolve across sessions?"

---

## 9. Session Lifecycle

### 9.1 Session Start

```python
def start_session(workspace: Workspace) -> Hash:
    # 1. Create a SessionStart event.
    event = Event(
        kind=EventKind.SessionStart,
        parents=[],
        inputs=[
            EventRef(hash=workspace.refs.read("student/mastery"), role="student_model"),
            EventRef(hash=workspace.refs.read("course/structure"), role="course"),
        ],
        outputs=[],
        trace=CallTrace(call_depth=0, ...),
        metadata=EventMetadata(timestamp=utcnow(), tags=[]),
    )
    event_hash = workspace.put(event)
    workspace.set_ref("session/current", event_hash)
    return event_hash
```

### 9.2 Turn Loop

Each student input → model response cycle is an iteration of the execution loop (Section 7.2). Events chain together via parent links:

```
SessionStart → StudentInput → ModelCall → [sub-calls...] → StudentModelUpdate → StudentInput → ...
```

### 9.3 Session End

```python
def end_session(workspace: Workspace, session_events: list[Hash]) -> Hash:
    event = Event(
        kind=EventKind.SessionEnd,
        parents=[session_events[-1]],  # last event in the session
        inputs=session_events,
        outputs=[],
        trace=CallTrace(call_depth=0, ...),
        metadata=EventMetadata(timestamp=utcnow(), tags=[]),
    )
    event_hash = workspace.put(event)

    # Archive the session ref.
    session_id = utcnow().strftime("%Y-%m-%d") + "-" + short_hash(event_hash)
    workspace.set_ref(f"session/{session_id}", event_hash)
    workspace.refs.delete("session/current")

    return event_hash
```

---

## 10. Merge Semantics

When a sub-call produces outputs that the parent needs to incorporate, merging occurs. Unlike Git (which merges text), merge here is domain-specific.

### 10.1 Merge Cases

| What's being merged | Policy |
|---|---|
| **Mastery estimates** | If parent and child both updated the same concept, take the more recent estimate (child wins, since it saw more specific evidence). |
| **Misconception annotations** | Union. Never discard a detected misconception. |
| **Lesson/problem suggestions** | Parent selects from child suggestions based on pedagogical strategy. |
| **Model outputs** | Concatenate or summarize, depending on the parent's prompt. |

### 10.2 Merge Events

A merge is recorded as an Event of kind `Merge`, with the sub-call results as inputs and the merged state as outputs. This preserves full provenance.

---

## 11. PyO3 Bridge

The Rust core is exposed to Python as a native module via PyO3/maturin.

### 11.1 Python API Surface

```python
import rlm_ws

# Workspace lifecycle
ws = rlm_ws.Workspace.init("/path/to/course")
ws = rlm_ws.Workspace.open("/path/to/course")

# Object I/O
atom = rlm_ws.Atom(
    kind="ConceptDefinition",
    text="Binary search is an O(log n) search algorithm...",
    tags=["algorithms", "search"],
)
h = ws.put(atom)
retrieved = ws.get_atom(h)

frame = rlm_ws.Frame(
    kind="Lesson",
    edges=[
        rlm_ws.Edge(label="CoversConcept", target=concept_hash, weight=None),
        rlm_ws.Edge(label="IncludesProblem", target=problem_hash, weight=None),
    ],
    label="Introduction to Binary Search",
)
fh = ws.put(frame)

# Refs
ws.set_ref("course/structure", course_frame_hash)
h = ws.get_ref_hash("student/mastery")

# Scoped views
scope = ws.scoped_view([concept_hash, student_hash])
atoms_in_scope = scope.atoms(kind="ConceptDefinition")

# Graph queries
neighbors = ws.graph.reverse_edges(concept_hash)
atoms = ws.graph.collect_atoms(lesson_hash, kinds=["ProblemStatement", "WorkedExample"])
call_tree = ws.graph.call_tree(root_event_hash)

# Index queries
recent = ws.index.recent_events(n=10, kind="ModelCall")
related = ws.index.by_concept(concept_hash)
similar = ws.index.nearest_neighbors(embedding_vec, k=5, kind="ConceptDefinition")

# Export/import
ws.export_json(root_hash, "/path/to/export.json")
ws.import_json("/path/to/import.json")

# GC
report = ws.gc()
print(f"Removed {report.removed_count} unreachable objects")
```

### 11.2 Type Mapping

| Rust | Python |
|---|---|
| `Hash` | `bytes` (32 bytes) with `__str__` → hex, `__repr__` → short hex |
| `Atom`, `Frame`, `Event` | Python classes with named fields |
| `AtomKind`, `FrameKind`, etc. | String enums |
| `Edge` | Python dataclass |
| `ScopedView` | Python object holding Arc reference to Rust data |
| `DateTime<Utc>` | `datetime.datetime` (UTC) |
| `serde_json::Value` | `dict` / `list` / `str` / `int` / `float` / `bool` / `None` |

---

## 12. Implementation Plan

### Phase 1: Object Store Foundation

**Deliverable:** A Rust crate that can create, read, and hash the four object types, manage refs, and persist to disk.

1. Define core types: `Hash`, `Atom`, `Frame`, `Event`, `Ref` with serde serialization.
2. Implement `Storable` trait and hash computation.
3. Implement `ObjectStore`: write, read, exists, with shard-based file layout.
4. Implement `RefStore`: read, write, delete, list, cas.
5. Implement `Workspace::init` and `Workspace::open`.
6. Write comprehensive tests: round-trip serialization, hash determinism, concurrent ref updates.

### Phase 2: Graph and Indexes

**Deliverable:** Graph traversal and SQLite secondary indexes.

1. Implement `Graph`: walk, reverse_edges, collect_atoms, session_events, call_tree.
2. Implement `Index`: SQLite schema, rebuild, incremental indexing.
3. Wire indexes into `Workspace::put` for automatic incremental updates.
4. Add garbage collection.
5. Test with synthetic course graphs (generate a small course, verify all queries return correct results).

### Phase 3: PyO3 Bridge

**Deliverable:** `pip install`-able Python module exposing the full Workspace API.

1. Set up maturin build.
2. Wrap all core types as Python classes.
3. Expose Workspace, ScopedView, Graph, Index to Python.
4. Write Python-side tests confirming parity with Rust tests.

### Phase 4: Retrieval System

**Deliverable:** Python retrieval framework with built-in strategies.

1. Implement RetrievalQuery, ScoredCandidate, RetrievalPolicy.
2. Implement strategies: GraphProximity, MasteryAware, TemporalRecency, PrerequisiteChain, InteractionHistory.
3. Implement SemanticSimilarity (requires embedding generation — use a local model or API).
4. Implement default policies per intent.
5. Test against synthetic courses with known-correct retrieval expectations.

### Phase 5: Execution Engine

**Deliverable:** Working recursive execution loop with event recording.

1. Implement PreparedCall construction.
2. Implement the execution loop with sub-call support.
3. Implement the model interaction protocol (structured output parsing).
4. Implement student model updates.
5. Implement session lifecycle (start, turn loop, end).
6. End-to-end test: run a 3-turn tutoring session against a real model, verify the event DAG is correct.

### Phase 6: Workspace Bootstrap Tools

**Deliverable:** CLI tools to initialize a course workspace from existing content.

1. `rlm-ws init` — create a new workspace.
2. `rlm-ws ingest` — parse markdown/text course materials into Atoms and Frames.
3. `rlm-ws inspect` — pretty-print objects, refs, graph structure.
4. `rlm-ws gc` — run garbage collection.
5. `rlm-ws export` / `rlm-ws import` — JSON round-tripping.

---

## 14. Plumbing-First Policy
1. The core store must remain boring, deterministic, and inspectable.
2. Derived data must never be required for correctness.
3. Mutable state must be minimized and made explicit.
4. Expensive or complex features should live at the edges, not in the storage model.
5. Optimize after real pain is observed, not before.

### 14.1 Resolution: Embeddings Are Derived, Optional, and Out-of-Band
Embeddings SHALL be treated as derived index data, not as part of object identity and not as a prerequisite for object writes.

#### Policy
- `Workspace::put` MUST succeed without requiring embedding generation.
- Embeddings MUST NOT participate in object hashing.
- Embeddings MUST be stored only in the secondary index layer or another rebuildable derived-data layer.
- Missing embeddings MUST NOT prevent retrieval; retrieval SHALL fall back to non-embedding strategies.
- Embedding generation SHOULD occur asynchronously after object creation, either:
  - eagerly but out-of-band via a background worker, or
  - lazily on first semantic query.

#### Consequences
- The Rust core remains self-contained and deterministic.
- The workspace can be written and inspected without network access or model availability.
- Embedding generation failures degrade retrieval quality, not system correctness.

#### Rationale
The object store is the source of truth. Embeddings are a convenience index. The storage engine should not require an ML model in the write path.

---

### 14.2 Resolution: Large Binary Content Is Stored Inline in v1
Binary payloads SHALL be stored inline in Atoms in the initial design.

#### Policy
- `AtomContent.binary` remains part of the stored object body in v1.
- The hash MUST continue to cover the raw binary bytes.
- The object model SHALL NOT introduce a separate large-file indirection mechanism in v1.
- The implementation MAY emit warnings or metrics for unusually large objects.
- A future external-blob mechanism MAY be added later, but only as an extension driven by demonstrated operational need.

#### Consequences
- The storage model remains uniform: all content is content-addressed and immutable.
- Inspection, export, import, and GC remain conceptually simple.
- Large media support is available immediately, even if not yet optimized.

#### Rationale
Most tutoring content is text. A separate LFS-style mechanism would add complexity before there is evidence that large binaries are a real problem.

---

### 14.3 Resolution: Concurrency Is Managed at Refs, Not by Making Objects Mutable
The system SHALL continue to use immutable object writes and mutable refs as the only synchronization point.

#### Policy
- Object writes MUST remain append-only and idempotent.
- Ref updates MUST be atomic.
- Compare-and-swap (`cas`) MUST be the primitive for safe concurrent ref updates.
- Concurrent updates that produce divergent immutable objects SHALL be represented explicitly and resolved by merge logic at the application layer.
- The Rust core SHALL NOT attempt to provide implicit semantic conflict resolution for student-model updates.
- Multi-step state changes involving multiple refs SHOULD be modeled as:
  1. write immutable objects first,
  2. record an Event,
  3. update the relevant ref(s) using CAS.

#### Consequences
- Concurrent writers do not corrupt stored objects.
- Ref contention is explicit and recoverable.
- Merge semantics remain domain-specific and observable through Events.

#### Rationale
Concurrency should be concentrated in the smallest possible mutable surface. Immutable objects are easy to reason about; mutable semantic state is not.

---

### 14.4 Resolution: The Default Embedding Index Is Simple, Swappable, and Non-Core
The initial embedding index SHALL use a simple brute-force implementation, with a clean abstraction boundary so that faster backends can be introduced later.

#### Policy
- SQLite-based brute-force nearest-neighbor search is the default implementation.
- The object store and graph model MUST remain independent of the embedding backend.
- The index layer SHOULD expose a backend abstraction so that future implementations can replace the default without changing callers.
- Approximate nearest-neighbor infrastructure MUST remain optional and non-core until performance data justifies it.

#### Consequences
- Small and medium workspaces remain easy to deploy.
- The project avoids premature dependency on specialized vector infrastructure.
- Scaling can be addressed later without redesigning the object model.

#### Rationale
A simple implementation that is correct and replaceable is preferable to a complex implementation justified only by hypothetical scale.

---

### 14.5 Resolution: The Execution Engine Uses Structured Commands, Not Prompt-Scraped Markup
The execution engine SHALL use a typed internal command representation. Free-text markup embedded in natural language SHALL NOT be the normative protocol.

#### Policy
- The execution engine MUST define an internal structured command schema for operations such as:
  - sub-call requests,
  - mastery updates,
  - retrieval requests,
  - merge requests.
- For providers supporting tool/function calling, adapters SHOULD map provider-native tool calls into the internal command schema.
- For providers without tool calling, the fallback protocol SHOULD be strict JSON, not ad hoc XML-like tags in free text.
- Parsing natural-language output for control instructions SHOULD be treated only as a last-resort compatibility mode.
- The Rust core SHALL remain unaware of model protocol details.

#### Consequences
- The machine interface becomes more robust and testable.
- Provider-specific quirks are isolated in adapters.
- The object model does not become coupled to a transient prompt format.

#### Rationale
If the machine needs structure, the protocol should provide structure directly.

---

### 14.6 Resolution: Shared Course Content and Per-Student Mutable State Are Separated
The logical model SHALL distinguish between shared immutable course content and per-student mutable state.

#### Policy
- Course structure refs (`course/...`) SHALL be treated as shared and effectively read-only during tutoring operation.
- Student state SHALL live in per-student namespaces, e.g.:
  - `student/{student_id}/mastery`
  - `student/{student_id}/session/current`
  - `student/{student_id}/session/{session_id}`
- The implementation SHOULD assume a single active writer per student namespace.
- Cross-student mutation of shared refs MUST be avoided during normal tutoring flows.
- A future deployment mode MAY further separate student state into overlays or per-student workspaces, but the logical separation is required now even if the physical store is shared.

#### Consequences
- Shared curriculum data is stable.
- Student-specific contention is localized.
- Multi-student deployments do not force global mutable coordination.

#### Rationale
The course is shared infrastructure. The student model is local evolving state. These should not be treated as the same kind of mutable thing.

---

## 14.7 Implementation Guidance
The following implementation choices follow directly from the above resolutions:

### Core Rust layer
The Rust core SHOULD contain only:
- object serialization and hashing,
- object storage and retrieval,
- ref operations,
- graph traversal,
- rebuildable indexes,
- scoped views,
- export/import,
- garbage collection.

The Rust core SHOULD NOT contain:
- embedding generation,
- vector-model dependencies,
- retrieval-policy logic,
- model-specific parsing logic,
- provider-specific tool protocols,
- tutoring pedagogy.

### Python layer
The Python layer SHOULD contain:
- retrieval policies,
- embedding generation jobs,
- execution orchestration,
- model-provider adapters,
- structured command parsing,
- student-model update policy,
- merge policy.
This preserves a clean plumbing/porcelain split.

---

## 14.8 Non-Goals for v1
The following are explicitly out of scope for the first implementation:
1. Requiring embeddings for correctness.
2. Adding a specialized large-file storage protocol before large binaries are proven problematic.
3. Building distributed locking or multi-writer transactional semantics into the core.
4. Making the object model depend on a vector database.
5. Making XML-like prompt markup the canonical execution protocol.
6. Treating all students as writers to one shared mutable tutoring state.

---

## 14.9 Summary of Final Decisions
| Question | Resolution |
|---|---|
| Embeddings eager vs lazy | Derived and out-of-band; writes never depend on them |
| Large binary content | Inline in v1 |
| Concurrent access | Immutable objects + CAS refs + explicit merges |
| Embedding index scaling | SQLite brute-force first; backend swappable |
| Model interaction protocol | Internal typed commands; tool use or strict JSON preferred |
| Multi-student deployment | Shared course content, per-student mutable namespaces |
