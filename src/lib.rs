// ============================================================================
// Crate-level lint policy: treat warnings as errors.
// ============================================================================
#![deny(warnings)]
#![deny(clippy::all)]
#![warn(clippy::pedantic)]
// Pedantic exceptions — these fire too often for our style.
#![allow(clippy::module_name_repetitions)]  // e.g., AtomKind inside types::Atom
#![allow(clippy::must_use_candidate)]       // too noisy for a library crate
#![allow(clippy::missing_errors_doc)]       // we'll add doc comments in a later pass
#![allow(clippy::missing_panics_doc)]

pub mod error;
pub mod hash;
pub mod types;
pub mod envelope;
pub mod store;
pub mod refs;
pub mod graph;
pub mod index;
pub mod workspace;

// Re-export the primary public API.
pub use error::{Error, Result};
pub use hash::Hash;
pub use types::{
    Atom, AtomContent, AtomKind, AtomMetadata,
    Frame, FrameKind, FrameMetadata, Edge, EdgeLabel,
    Event, EventKind, EventMetadata, EventRef, CallTrace,
    ObjectType,
};
pub use envelope::Storable;
pub use store::ObjectStore;
pub use refs::{Ref, RefStore};
pub use graph::{Graph, CallTreeNode, Direction};
pub use index::Index;
pub use workspace::{Workspace, GcReport};
