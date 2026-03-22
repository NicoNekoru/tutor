use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::hash::Hash;

/// Custom serde module: serializes `serde_json::Value` as a JSON string
/// in non-human-readable formats (bincode), and directly in human-readable
/// formats (`serde_json`). Works around bincode's lack of `deserialize_any`.
mod json_value_compat {
    use serde::{self, Deserialize, Deserializer, Serialize, Serializer};

    pub fn serialize<S>(value: &Option<serde_json::Value>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if serializer.is_human_readable() {
            value.serialize(serializer)
        } else {
            let as_string = value
                .as_ref()
                .map(|v| serde_json::to_string(v).unwrap_or_default());
            as_string.serialize(serializer)
        }
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<serde_json::Value>, D::Error>
    where
        D: Deserializer<'de>,
    {
        if deserializer.is_human_readable() {
            Option::<serde_json::Value>::deserialize(deserializer)
        } else {
            let as_string = Option::<String>::deserialize(deserializer)?;
            match as_string {
                Some(s) => {
                    let val: serde_json::Value =
                        serde_json::from_str(&s).map_err(serde::de::Error::custom)?;
                    Ok(Some(val))
                }
                None => Ok(None),
            }
        }
    }
}

// ============================================================================
// Atom
// ============================================================================

/// The smallest unit of content. A leaf node in the object graph.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Atom {
    pub kind: AtomKind,
    pub content: AtomContent,
    pub metadata: AtomMetadata,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub enum AtomKind {
    ConceptDefinition,
    LessonBody,
    ProblemStatement,
    WorkedExample,
    StudentResponse,
    ModelOutput,
    Annotation,
    Config,
    Blob,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AtomContent {
    /// Primary text content.
    pub text: String,
    /// Optional structured data (JSON-compatible).
    #[serde(default, with = "json_value_compat")]
    pub structured: Option<serde_json::Value>,
    /// Optional binary payload.
    pub binary: Option<Vec<u8>>,
    /// MIME type for binary content.
    pub mime_type: Option<String>,
}

impl AtomContent {
    /// Create a text-only atom content.
    pub fn text(text: impl Into<String>) -> Self {
        AtomContent {
            text: text.into(),
            structured: None,
            binary: None,
            mime_type: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AtomMetadata {
    pub created_at: DateTime<Utc>,
    pub tags: Vec<String>,
}

impl AtomMetadata {
    pub fn now() -> Self {
        AtomMetadata {
            created_at: Utc::now(),
            tags: Vec::new(),
        }
    }

    #[must_use]
    pub fn with_tags(mut self, tags: Vec<String>) -> Self {
        self.tags = tags;
        self
    }
}

// ============================================================================
// Frame
// ============================================================================

/// A structured collection of typed edges to other objects.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Frame {
    pub kind: FrameKind,
    pub edges: Vec<Edge>,
    pub metadata: FrameMetadata,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub enum FrameKind {
    Lesson,
    Module,
    Course,
    StudentModel,
    SessionSnapshot,
    RetrievalScope,
    CallContext,
    Collection,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Edge {
    pub label: EdgeLabel,
    pub target: Hash,
    pub weight: Option<f64>,
    #[serde(default, with = "json_value_compat")]
    pub annotation: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum EdgeLabel {
    // Curricular structure
    Prerequisite,
    CoversConcept,
    Contains,
    IncludesProblem,
    IncludesExample,

    // Student model
    MasteryEstimate,
    Misconception,
    InteractionRecord,

    // Session and execution
    ProducedOutput,
    ReceivedInput,
    UsedScope,
    SpawnedChild,

    // Retrieval and scoping
    InScope,
    RetrievalPolicy,

    // Generic
    Custom,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct FrameMetadata {
    pub created_at: DateTime<Utc>,
    pub tags: Vec<String>,
    pub label: Option<String>,
    /// If true, the label participates in hash computation.
    #[serde(default)]
    pub label_in_hash: bool,
}

impl FrameMetadata {
    pub fn now() -> Self {
        FrameMetadata {
            created_at: Utc::now(),
            tags: Vec::new(),
            label: None,
            label_in_hash: false,
        }
    }

    #[must_use]
    pub fn with_label(mut self, label: impl Into<String>, in_hash: bool) -> Self {
        self.label = Some(label.into());
        self.label_in_hash = in_hash;
        self
    }
}

// ============================================================================
// Event
// ============================================================================

/// Records that something happened. Forms the temporal backbone (a DAG).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Event {
    pub kind: EventKind,
    pub parents: Vec<Hash>,
    pub inputs: Vec<EventRef>,
    pub outputs: Vec<EventRef>,
    pub trace: CallTrace,
    pub metadata: EventMetadata,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub enum EventKind {
    SessionStart,
    SessionEnd,
    ModelCall,
    StudentInput,
    StudentModelUpdate,
    RetrievalPerformed,
    Merge,
    Admin,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EventRef {
    pub hash: Hash,
    pub role: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CallTrace {
    pub model: Option<String>,
    pub prompt_template: Option<String>,
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    pub latency_ms: Option<u64>,
    pub retrieval_scope: Option<Hash>,
    pub call_depth: u32,
    pub parent_call: Option<Hash>,
    #[serde(default, with = "json_value_compat")]
    pub extra: Option<serde_json::Value>,
}

impl CallTrace {
    pub fn empty() -> Self {
        CallTrace {
            model: None,
            prompt_template: None,
            input_tokens: None,
            output_tokens: None,
            latency_ms: None,
            retrieval_scope: None,
            call_depth: 0,
            parent_call: None,
            extra: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EventMetadata {
    pub timestamp: DateTime<Utc>,
    pub tags: Vec<String>,
}

impl EventMetadata {
    pub fn now() -> Self {
        EventMetadata {
            timestamp: Utc::now(),
            tags: Vec::new(),
        }
    }
}

// ============================================================================
// ObjectType discriminant (for the envelope)
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum ObjectType {
    Atom = 0x01,
    Frame = 0x02,
    Event = 0x03,
}

impl ObjectType {
    pub fn from_byte(b: u8) -> Option<Self> {
        match b {
            0x01 => Some(ObjectType::Atom),
            0x02 => Some(ObjectType::Frame),
            0x03 => Some(ObjectType::Event),
            _ => None,
        }
    }
}
