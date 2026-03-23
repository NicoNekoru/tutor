use std::path::PathBuf;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum Error {
    #[error("IO error at {path:?}: {source}")]
    Io {
        source: std::io::Error,
        path: PathBuf,
    },

    #[error("Serialization error: {0}")]
    Serialization(String),

    #[error("Deserialization error: {0}")]
    Deserialization(String),

    #[error("Object not found: {0}")]
    NotFound(String),

    #[error("Invalid object envelope: {0}")]
    InvalidEnvelope(String),

    #[error("Ref conflict: {name} expected {expected} but found {actual}")]
    RefConflict {
        name: String,
        expected: String,
        actual: String,
    },

    #[error("Workspace already exists at {0}")]
    WorkspaceExists(PathBuf),

    #[error("Workspace not found at {0}")]
    WorkspaceNotFound(PathBuf),

    #[error("Invalid hash: {0}")]
    InvalidHash(String),

    #[error("Type mismatch: expected {expected}, found {found}")]
    TypeMismatch { expected: String, found: String },
}

pub type Result<T> = std::result::Result<T, Error>;

impl Error {
    pub fn io(source: std::io::Error, path: impl Into<PathBuf>) -> Self {
        Error::Io {
            source,
            path: path.into(),
        }
    }
}
