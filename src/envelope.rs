use crate::error::{Error, Result};
use crate::hash::Hash;
use crate::types::{Atom, Event, Frame, ObjectType};

/// The on-disk envelope wrapping every stored object.
///
/// Layout:
///   Magic   "RLMW" (4 bytes)
///   Version u8
///   Type    u8
///   Flags   u8  (bit 0 = compressed)
///   Reserved u8
///   Length  u64 (little-endian, content length)
///   Content [u8; Length]
pub struct ObjectEnvelope {
    pub version: u8,
    pub object_type: ObjectType,
    pub compressed: bool,
    pub content: Vec<u8>,
}

const MAGIC: &[u8; 4] = b"RLMW";
const CURRENT_VERSION: u8 = 1;

impl ObjectEnvelope {
    /// Serialize an envelope to bytes for writing to disk.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut buf = Vec::with_capacity(16 + self.content.len());
        buf.extend_from_slice(MAGIC);
        buf.push(self.version);
        buf.push(self.object_type as u8);
        buf.push(if self.compressed { 1 } else { 0 });
        buf.push(0); // reserved
        buf.extend_from_slice(&(self.content.len() as u64).to_le_bytes());
        buf.extend_from_slice(&self.content);
        buf
    }

    /// Parse an envelope from bytes read from disk.
    pub fn from_bytes(data: &[u8]) -> Result<Self> {
        if data.len() < 16 {
            return Err(Error::InvalidEnvelope(format!(
                "too short: {} bytes",
                data.len()
            )));
        }
        if &data[0..4] != MAGIC {
            return Err(Error::InvalidEnvelope("bad magic bytes".into()));
        }
        let version = data[4];
        if version != CURRENT_VERSION {
            return Err(Error::InvalidEnvelope(format!(
                "unsupported version: {}",
                version
            )));
        }
        let object_type = ObjectType::from_byte(data[5])
            .ok_or_else(|| Error::InvalidEnvelope(format!("unknown type: 0x{:02x}", data[5])))?;
        let compressed = data[6] & 1 != 0;
        let content_len = u64::from_le_bytes(data[8..16].try_into().unwrap()) as usize;
        if data.len() < 16 + content_len {
            return Err(Error::InvalidEnvelope(format!(
                "truncated: expected {} content bytes, got {}",
                content_len,
                data.len() - 16
            )));
        }
        Ok(ObjectEnvelope {
            version,
            object_type,
            compressed,
            content: data[16..16 + content_len].to_vec(),
        })
    }
}

/// Trait for types that can be stored in the object store.
///
/// The contract:
/// 1. `to_hashable_bytes` returns the canonical serialized form used for hashing.
/// 2. `from_hashable_bytes` deserializes from that canonical form.
/// 3. The hash is ALWAYS computed over the output of `to_hashable_bytes`.
/// 4. `TYPE_CODE` identifies the object type in the envelope.
pub trait Storable: Sized {
    const TYPE_CODE: ObjectType;

    /// Serialize to the canonical byte form used for hashing and storage.
    fn to_hashable_bytes(&self) -> Result<Vec<u8>>;

    /// Deserialize from the canonical byte form.
    fn from_hashable_bytes(data: &[u8]) -> Result<Self>;

    /// Compute the content hash.
    fn compute_hash(&self) -> Result<Hash> {
        let bytes = self.to_hashable_bytes()?;
        Ok(Hash::compute(&bytes))
    }
}

impl Storable for Atom {
    const TYPE_CODE: ObjectType = ObjectType::Atom;

    fn to_hashable_bytes(&self) -> Result<Vec<u8>> {
        bincode::serialize(self).map_err(|e| Error::Serialization(e.to_string()))
    }

    fn from_hashable_bytes(data: &[u8]) -> Result<Self> {
        bincode::deserialize(data).map_err(|e| Error::Deserialization(e.to_string()))
    }
}

impl Storable for Frame {
    const TYPE_CODE: ObjectType = ObjectType::Frame;

    fn to_hashable_bytes(&self) -> Result<Vec<u8>> {
        // Per spec: edges are sorted by target hash for deterministic hashing.
        let mut canonical = self.clone();
        canonical.edges.sort_by(|a, b| a.target.cmp(&b.target));
        bincode::serialize(&canonical).map_err(|e| Error::Serialization(e.to_string()))
    }

    fn from_hashable_bytes(data: &[u8]) -> Result<Self> {
        bincode::deserialize(data).map_err(|e| Error::Deserialization(e.to_string()))
    }
}

impl Storable for Event {
    const TYPE_CODE: ObjectType = ObjectType::Event;

    fn to_hashable_bytes(&self) -> Result<Vec<u8>> {
        bincode::serialize(self).map_err(|e| Error::Serialization(e.to_string()))
    }

    fn from_hashable_bytes(data: &[u8]) -> Result<Self> {
        bincode::deserialize(data).map_err(|e| Error::Deserialization(e.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;
    use chrono::{DateTime, Utc};

    #[test]
    fn test_envelope_roundtrip() {
        let env = ObjectEnvelope {
            version: CURRENT_VERSION,
            object_type: ObjectType::Atom,
            compressed: false,
            content: b"hello world".to_vec(),
        };
        let bytes = env.to_bytes();
        let env2 = ObjectEnvelope::from_bytes(&bytes).unwrap();
        assert_eq!(env2.version, CURRENT_VERSION);
        assert_eq!(env2.object_type, ObjectType::Atom);
        assert!(!env2.compressed);
        assert_eq!(env2.content, b"hello world");
    }

    #[test]
    fn test_envelope_bad_magic() {
        let mut bytes = ObjectEnvelope {
            version: CURRENT_VERSION,
            object_type: ObjectType::Atom,
            compressed: false,
            content: vec![],
        }
        .to_bytes();
        bytes[0] = b'X';
        assert!(ObjectEnvelope::from_bytes(&bytes).is_err());
    }

    #[test]
    fn test_envelope_truncated() {
        assert!(ObjectEnvelope::from_bytes(&[0u8; 10]).is_err());
    }

    #[test]
    fn test_atom_storable_deterministic() {
        let atom = Atom {
            kind: AtomKind::ConceptDefinition,
            content: AtomContent::text("Binary search is O(log n)"),
            metadata: AtomMetadata {
                created_at: DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc),
                tags: vec!["algorithms".into()],
            },
        };
        let h1 = atom.compute_hash().unwrap();
        let h2 = atom.compute_hash().unwrap();
        assert_eq!(h1, h2, "Same atom must always hash the same");
    }

    #[test]
    fn test_atom_different_kind_different_hash() {
        let ts = DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let atom1 = Atom {
            kind: AtomKind::ConceptDefinition,
            content: AtomContent::text("same text"),
            metadata: AtomMetadata {
                created_at: ts,
                tags: vec![],
            },
        };
        let atom2 = Atom {
            kind: AtomKind::LessonBody,
            content: AtomContent::text("same text"),
            metadata: AtomMetadata {
                created_at: ts,
                tags: vec![],
            },
        };
        assert_ne!(
            atom1.compute_hash().unwrap(),
            atom2.compute_hash().unwrap(),
            "Different kinds must produce different hashes"
        );
    }

    #[test]
    fn test_atom_serialization_roundtrip() {
        let atom = Atom {
            kind: AtomKind::ProblemStatement,
            content: AtomContent {
                text: "What is 2+2?".into(),
                structured: Some(serde_json::json!({"difficulty": "easy"})),
                binary: Some(vec![0xDE, 0xAD, 0xBE, 0xEF]),
                mime_type: Some("application/octet-stream".into()),
            },
            metadata: AtomMetadata {
                created_at: DateTime::parse_from_rfc3339("2026-03-21T00:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc),
                tags: vec!["math".into(), "easy".into()],
            },
        };
        let bytes = atom.to_hashable_bytes().unwrap();
        let atom2 = Atom::from_hashable_bytes(&bytes).unwrap();
        assert_eq!(atom, atom2);
    }

    #[test]
    fn test_frame_edge_order_independence() {
        let ts = DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let h_a = Hash::compute(b"concept_a");
        let h_b = Hash::compute(b"concept_b");

        let frame1 = Frame {
            kind: FrameKind::Lesson,
            edges: vec![
                Edge { label: EdgeLabel::CoversConcept, target: h_a, weight: None, annotation: None },
                Edge { label: EdgeLabel::CoversConcept, target: h_b, weight: None, annotation: None },
            ],
            metadata: FrameMetadata { created_at: ts, tags: vec![], label: None, label_in_hash: false },
        };

        let frame2 = Frame {
            kind: FrameKind::Lesson,
            edges: vec![
                Edge { label: EdgeLabel::CoversConcept, target: h_b, weight: None, annotation: None },
                Edge { label: EdgeLabel::CoversConcept, target: h_a, weight: None, annotation: None },
            ],
            metadata: FrameMetadata { created_at: ts, tags: vec![], label: None, label_in_hash: false },
        };

        assert_eq!(
            frame1.compute_hash().unwrap(),
            frame2.compute_hash().unwrap(),
            "Frame hash must be independent of edge insertion order"
        );
    }

    #[test]
    fn test_frame_serialization_roundtrip() {
        let h = Hash::compute(b"target");
        let frame = Frame {
            kind: FrameKind::StudentModel,
            edges: vec![Edge {
                label: EdgeLabel::MasteryEstimate,
                target: h,
                weight: Some(0.73),
                annotation: Some(serde_json::json!({"reason": "quiz score"})),
            }],
            metadata: FrameMetadata {
                created_at: Utc::now(),
                tags: vec!["student".into()],
                label: Some("test-model".into()),
                label_in_hash: true,
            },
        };
        let bytes = frame.to_hashable_bytes().unwrap();
        let frame2 = Frame::from_hashable_bytes(&bytes).unwrap();
        // Note: edges may be reordered by to_hashable_bytes (sorted by target),
        // so we compare the deserialized form which is the sorted form.
        assert_eq!(frame2.kind, frame.kind);
        assert_eq!(frame2.edges.len(), 1);
        assert_eq!(frame2.edges[0].target, h);
    }

    #[test]
    fn test_event_serialization_roundtrip() {
        let event = Event {
            kind: EventKind::ModelCall,
            parents: vec![Hash::compute(b"parent")],
            inputs: vec![EventRef {
                hash: Hash::compute(b"input"),
                role: "context".into(),
            }],
            outputs: vec![EventRef {
                hash: Hash::compute(b"output"),
                role: "response".into(),
            }],
            trace: CallTrace {
                model: Some("claude-sonnet-4-20250514".into()),
                prompt_template: None,
                input_tokens: Some(1500),
                output_tokens: Some(300),
                latency_ms: Some(2000),
                retrieval_scope: None,
                call_depth: 1,
                parent_call: Some(Hash::compute(b"parent_call")),
                extra: None,
            },
            metadata: EventMetadata {
                timestamp: Utc::now(),
                tags: vec![],
            },
        };
        let bytes = event.to_hashable_bytes().unwrap();
        let event2 = Event::from_hashable_bytes(&bytes).unwrap();
        assert_eq!(event, event2);
    }
}
