// ============================================================================
// Crate-level lint policy: treat warnings as errors.
// ============================================================================
#![deny(warnings)]
#![deny(clippy::all)]
#![warn(clippy::pedantic)]
// Pedantic exceptions — these fire too often for our style.
#![allow(clippy::module_name_repetitions)] // e.g., AtomKind inside types::Atom
#![allow(clippy::must_use_candidate)] // too noisy for a library crate
#![allow(clippy::missing_errors_doc)] // we'll add doc comments in a later pass
#![allow(clippy::missing_panics_doc)]

pub mod envelope;
pub mod error;
pub mod graph;
pub mod hash;
pub mod index;
#[cfg(feature = "python")]
pub mod pybridge;
pub mod refs;
pub mod store;
pub mod types;
pub mod workspace;

// Re-export the primary public API.
pub use envelope::Storable;
pub use error::{Error, Result};
pub use graph::{CallTreeNode, Direction, Graph};
pub use hash::Hash;
pub use index::Index;
pub use refs::{Ref, RefStore};
pub use store::ObjectStore;
pub use types::{
    Atom, AtomContent, AtomKind, AtomMetadata, CallTrace, Edge, EdgeLabel, Event, EventKind,
    EventMetadata, EventRef, Frame, FrameKind, FrameMetadata, ObjectType,
};
pub use workspace::{GcReport, Workspace};
