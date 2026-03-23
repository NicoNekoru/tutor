use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

use crate::envelope::{ObjectEnvelope, Storable};
use crate::error::{Error, Result};
use crate::hash::Hash;
use crate::types::ObjectType;

/// Content-addressable object store backed by the filesystem.
///
/// Objects are stored at: `{root}/objects/{shard}/{hex_hash}`
/// where shard is the first 2 hex characters of the hash.
///
/// Writes are atomic: serialize → write to tmp → rename into place.
pub struct ObjectStore {
    /// Path to .rlm/objects/
    objects_dir: PathBuf,
    /// Path to .rlm/tmp/
    tmp_dir: PathBuf,
}

impl ObjectStore {
    /// Open an object store. Assumes the directories exist.
    pub fn open(rlm_root: &Path) -> Result<Self> {
        let objects_dir = rlm_root.join("objects");
        let tmp_dir = rlm_root.join("tmp");
        Ok(ObjectStore {
            objects_dir,
            tmp_dir,
        })
    }

    /// Ensure required directories exist.
    pub fn init_dirs(&self) -> Result<()> {
        fs::create_dir_all(&self.objects_dir).map_err(|e| Error::io(e, &self.objects_dir))?;
        fs::create_dir_all(&self.tmp_dir).map_err(|e| Error::io(e, &self.tmp_dir))?;
        Ok(())
    }

    /// Write an object to the store. Returns the content hash.
    /// If the object already exists (same hash), this is an idempotent no-op.
    pub fn write<T: Storable>(&self, obj: &T) -> Result<Hash> {
        let hashable_bytes = obj.to_hashable_bytes()?;
        let hash = Hash::compute(&hashable_bytes);

        // Check if already exists (idempotent).
        let dest = self.object_path(&hash);
        if dest.exists() {
            return Ok(hash);
        }

        // Build envelope.
        let envelope = ObjectEnvelope {
            version: 1,
            object_type: T::TYPE_CODE,
            compressed: false, // v1: no compression
            content: hashable_bytes,
        };
        let envelope_bytes = envelope.to_bytes();

        // Atomic write: tmp file → rename.
        let shard_dir = dest.parent().unwrap();
        fs::create_dir_all(shard_dir).map_err(|e| Error::io(e, shard_dir))?;

        let tmp_path = self.tmp_dir.join(format!("write_{}", hash.short()));
        fs::write(&tmp_path, envelope_bytes).map_err(|e| Error::io(e, &tmp_path))?;
        fs::rename(&tmp_path, &dest).map_err(|e| Error::io(e, &dest))?;

        Ok(hash)
    }

    /// Read an object by hash. Returns None if not found.
    pub fn read<T: Storable>(&self, hash: &Hash) -> Result<Option<T>> {
        let path = self.object_path(hash);
        let data = match fs::read(&path) {
            Ok(d) => d,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(Error::io(e, &path)),
        };

        let envelope = ObjectEnvelope::from_bytes(&data)?;

        // Type check.
        if envelope.object_type != T::TYPE_CODE {
            return Err(Error::TypeMismatch {
                expected: format!("{:?}", T::TYPE_CODE),
                found: format!("{:?}", envelope.object_type),
            });
        }

        // Verify hash integrity.
        let computed = Hash::compute(&envelope.content);
        if computed != *hash {
            return Err(Error::InvalidEnvelope(format!(
                "hash mismatch: expected {}, computed {}",
                hash.short(),
                computed.short()
            )));
        }

        let obj = T::from_hashable_bytes(&envelope.content)?;
        Ok(Some(obj))
    }

    /// Read a raw envelope without deserializing the content.
    pub fn read_raw(&self, hash: &Hash) -> Result<Option<ObjectEnvelope>> {
        let path = self.object_path(hash);
        let data = match fs::read(&path) {
            Ok(d) => d,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(Error::io(e, &path)),
        };
        let envelope = ObjectEnvelope::from_bytes(&data)?;
        Ok(Some(envelope))
    }

    /// Check if an object exists without reading it.
    pub fn exists(&self, hash: &Hash) -> bool {
        self.object_path(hash).exists()
    }

    /// Get the filesystem path for an object hash.
    fn object_path(&self, hash: &Hash) -> PathBuf {
        let hex = hash.to_hex();
        self.objects_dir.join(&hex[..2]).join(&hex[2..])
    }

    /// Iterate all stored object hashes.
    pub fn all_hashes(&self) -> Result<Vec<Hash>> {
        let mut hashes = Vec::new();
        let entries = match fs::read_dir(&self.objects_dir) {
            Ok(e) => e,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(hashes),
            Err(e) => return Err(Error::io(e, &self.objects_dir)),
        };
        for shard_entry in entries {
            let shard_entry = shard_entry.map_err(|e| Error::io(e, &self.objects_dir))?;
            let shard_name = shard_entry.file_name();
            let shard_str = shard_name.to_string_lossy();
            if shard_str.len() != 2 {
                continue;
            }
            let sub_entries =
                fs::read_dir(shard_entry.path()).map_err(|e| Error::io(e, shard_entry.path()))?;
            for obj_entry in sub_entries {
                let obj_entry = obj_entry.map_err(|e| Error::io(e, shard_entry.path()))?;
                let obj_name = obj_entry.file_name();
                let obj_str = obj_name.to_string_lossy();
                let full_hex = format!("{shard_str}{obj_str}");
                if let Ok(hash) = Hash::from_hex(&full_hex) {
                    hashes.push(hash);
                }
            }
        }
        Ok(hashes)
    }

    /// Remove an object by hash. Returns true if it existed.
    pub fn remove(&self, hash: &Hash) -> Result<bool> {
        let path = self.object_path(hash);
        match fs::remove_file(&path) {
            Ok(()) => Ok(true),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(e) => Err(Error::io(e, &path)),
        }
    }
}

/// Collect all hashes reachable from the given roots by following
/// edges in Frames and parent/input/output links in Events.
pub fn reachable_from(store: &ObjectStore, roots: &[Hash]) -> Result<HashSet<Hash>> {
    let mut visited = HashSet::new();
    let mut queue: Vec<Hash> = roots.to_vec();

    while let Some(hash) = queue.pop() {
        if !visited.insert(hash) {
            continue;
        }
        if let Some(envelope) = store.read_raw(&hash)? {
            match envelope.object_type {
                ObjectType::Atom => {
                    // Atoms are leaf nodes, no references to follow.
                }
                ObjectType::Frame => {
                    if let Ok(frame) =
                        <crate::types::Frame as Storable>::from_hashable_bytes(&envelope.content)
                    {
                        for edge in &frame.edges {
                            queue.push(edge.target);
                        }
                    }
                }
                ObjectType::Event => {
                    if let Ok(event) =
                        <crate::types::Event as Storable>::from_hashable_bytes(&envelope.content)
                    {
                        for parent in &event.parents {
                            queue.push(*parent);
                        }
                        for input in &event.inputs {
                            queue.push(input.hash);
                        }
                        for output in &event.outputs {
                            queue.push(output.hash);
                        }
                        if let Some(scope) = &event.trace.retrieval_scope {
                            queue.push(*scope);
                        }
                        if let Some(parent_call) = &event.trace.parent_call {
                            queue.push(*parent_call);
                        }
                    }
                }
            }
        }
    }

    Ok(visited)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;
    use chrono::{DateTime, Utc};
    use tempfile::TempDir;

    fn setup() -> (TempDir, ObjectStore) {
        let dir = TempDir::new().unwrap();
        let rlm_root = dir.path().join(".rlm");
        fs::create_dir_all(&rlm_root).unwrap();
        let store = ObjectStore::open(&rlm_root).unwrap();
        store.init_dirs().unwrap();
        (dir, store)
    }

    fn make_atom(text: &str) -> Atom {
        Atom {
            kind: AtomKind::ConceptDefinition,
            content: AtomContent::text(text),
            metadata: AtomMetadata {
                created_at: DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc),
                tags: vec![],
            },
        }
    }

    #[test]
    fn test_write_read_atom() {
        let (_dir, store) = setup();
        let atom = make_atom("Binary search is O(log n)");
        let hash = store.write(&atom).unwrap();
        let retrieved: Atom = store.read(&hash).unwrap().unwrap();
        assert_eq!(atom, retrieved);
    }

    #[test]
    fn test_write_idempotent() {
        let (_dir, store) = setup();
        let atom = make_atom("test");
        let h1 = store.write(&atom).unwrap();
        let h2 = store.write(&atom).unwrap();
        assert_eq!(
            h1, h2,
            "Writing the same object twice must return the same hash"
        );
    }

    #[test]
    fn test_read_nonexistent() {
        let (_dir, store) = setup();
        let hash = Hash::compute(b"does not exist");
        let result: Option<Atom> = store.read(&hash).unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn test_exists() {
        let (_dir, store) = setup();
        let atom = make_atom("exists test");
        let hash = store.write(&atom).unwrap();
        assert!(store.exists(&hash));
        assert!(!store.exists(&Hash::compute(b"nope")));
    }

    #[test]
    fn test_type_mismatch() {
        let (_dir, store) = setup();
        let atom = make_atom("type mismatch");
        let hash = store.write(&atom).unwrap();
        // Try to read as Frame
        let result = store.read::<Frame>(&hash);
        assert!(result.is_err());
    }

    #[test]
    fn test_write_read_frame() {
        let (_dir, store) = setup();
        let concept_hash = store.write(&make_atom("concept")).unwrap();
        let frame = Frame {
            kind: FrameKind::Lesson,
            edges: vec![Edge {
                label: EdgeLabel::CoversConcept,
                target: concept_hash,
                weight: None,
                annotation: None,
            }],
            metadata: FrameMetadata {
                created_at: DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc),
                tags: vec![],
                label: Some("intro-lesson".into()),
                label_in_hash: true,
            },
        };
        let hash = store.write(&frame).unwrap();
        let retrieved: Frame = store.read(&hash).unwrap().unwrap();
        assert_eq!(retrieved.kind, FrameKind::Lesson);
        assert_eq!(retrieved.edges.len(), 1);
        assert_eq!(retrieved.edges[0].target, concept_hash);
    }

    #[test]
    fn test_write_read_event() {
        let (_dir, store) = setup();
        let event = Event {
            kind: EventKind::SessionStart,
            parents: vec![],
            inputs: vec![],
            outputs: vec![],
            trace: CallTrace::empty(),
            metadata: EventMetadata {
                timestamp: DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc),
                tags: vec![],
            },
        };
        let hash = store.write(&event).unwrap();
        let retrieved: Event = store.read(&hash).unwrap().unwrap();
        assert_eq!(event, retrieved);
    }

    #[test]
    fn test_all_hashes() {
        let (_dir, store) = setup();
        let h1 = store.write(&make_atom("one")).unwrap();
        let h2 = store.write(&make_atom("two")).unwrap();
        let h3 = store.write(&make_atom("three")).unwrap();
        let mut all = store.all_hashes().unwrap();
        all.sort();
        let mut expected = vec![h1, h2, h3];
        expected.sort();
        assert_eq!(all, expected);
    }

    #[test]
    fn test_remove() {
        let (_dir, store) = setup();
        let hash = store.write(&make_atom("removable")).unwrap();
        assert!(store.exists(&hash));
        assert!(store.remove(&hash).unwrap());
        assert!(!store.exists(&hash));
        assert!(!store.remove(&hash).unwrap()); // second remove returns false
    }

    #[test]
    fn test_hash_integrity_check() {
        let (_dir, store) = setup();
        let atom = make_atom("integrity");
        let hash = store.write(&atom).unwrap();

        // Corrupt the file.
        let hex = hash.to_hex();
        let path = store.objects_dir.join(&hex[..2]).join(&hex[2..]);
        let mut data = fs::read(&path).unwrap();
        // Flip a byte in the content area (past the 16-byte header).
        if data.len() > 20 {
            data[20] ^= 0xFF;
        }
        fs::write(&path, &data).unwrap();

        // Read should detect the corruption.
        let result = store.read::<Atom>(&hash);
        assert!(result.is_err(), "Corrupted object should fail hash check");
    }

    #[test]
    fn test_reachable_from() {
        let (_dir, store) = setup();

        // Build a small graph: course → lesson → concept
        let concept = make_atom("concept A");
        let ch = store.write(&concept).unwrap();

        let lesson = Frame {
            kind: FrameKind::Lesson,
            edges: vec![Edge {
                label: EdgeLabel::CoversConcept,
                target: ch,
                weight: None,
                annotation: None,
            }],
            metadata: FrameMetadata {
                created_at: Utc::now(),
                tags: vec![],
                label: None,
                label_in_hash: false,
            },
        };
        let lh = store.write(&lesson).unwrap();

        let course = Frame {
            kind: FrameKind::Course,
            edges: vec![Edge {
                label: EdgeLabel::Contains,
                target: lh,
                weight: None,
                annotation: None,
            }],
            metadata: FrameMetadata {
                created_at: Utc::now(),
                tags: vec![],
                label: None,
                label_in_hash: false,
            },
        };
        let course_h = store.write(&course).unwrap();

        // Also write an orphan (not reachable from course).
        let orphan = make_atom("orphan");
        let orphan_h = store.write(&orphan).unwrap();

        let reachable = reachable_from(&store, &[course_h]).unwrap();
        assert!(reachable.contains(&course_h));
        assert!(reachable.contains(&lh));
        assert!(reachable.contains(&ch));
        assert!(
            !reachable.contains(&orphan_h),
            "Orphan should not be reachable"
        );
    }
}
