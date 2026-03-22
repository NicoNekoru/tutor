use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use crate::envelope::Storable;
use crate::error::{Error, Result};
use crate::hash::Hash;
use crate::refs::RefStore;
use crate::store::{reachable_from, ObjectStore};
use crate::types::{Atom, Event, Frame};

const CONFIG_TEMPLATE: &str = r#"[workspace]
version = 1

[hashing]
algorithm = "sha256"

[serialization]
format = "bincode"
"#;

/// Report from garbage collection.
#[derive(Debug)]
pub struct GcReport {
    pub total_objects: usize,
    pub reachable_objects: usize,
    pub removed_objects: usize,
    pub removed_hashes: Vec<Hash>,
}

/// The top-level workspace handle. Owns the object store, ref store, and index.
pub struct Workspace {
    pub store: ObjectStore,
    pub refs: RefStore,
    pub index: crate::index::Index,
    root: PathBuf,
}

impl Workspace {
    /// Get a Graph handle for traversal operations.
    pub fn graph(&self) -> crate::graph::Graph<'_> {
        crate::graph::Graph::new(&self.store)
    }

    /// Initialize a new workspace at the given path.
    /// Creates the .rlm/ directory and all subdirectories.
    pub fn init(path: &Path) -> Result<Self> {
        let rlm_root = path.join(".rlm");
        if rlm_root.exists() {
            return Err(Error::WorkspaceExists(path.to_path_buf()));
        }

        fs::create_dir_all(&rlm_root).map_err(|e| Error::io(e, &rlm_root))?;

        let store = ObjectStore::open(&rlm_root)?;
        store.init_dirs()?;

        let refs = RefStore::open(&rlm_root)?;
        refs.init_dirs()?;

        // Write config.
        let config_path = rlm_root.join("config");
        let mut f = fs::File::create(&config_path).map_err(|e| Error::io(e, &config_path))?;
        f.write_all(CONFIG_TEMPLATE.as_bytes())
            .map_err(|e| Error::io(e, &config_path))?;

        let index = crate::index::Index::open(&rlm_root)?;

        Ok(Workspace {
            store,
            refs,
            index,
            root: path.to_path_buf(),
        })
    }

    /// Open an existing workspace.
    pub fn open(path: &Path) -> Result<Self> {
        let rlm_root = path.join(".rlm");
        if !rlm_root.exists() {
            return Err(Error::WorkspaceNotFound(path.to_path_buf()));
        }

        let store = ObjectStore::open(&rlm_root)?;
        let refs = RefStore::open(&rlm_root)?;
        let index = crate::index::Index::open(&rlm_root)?;

        Ok(Workspace {
            store,
            refs,
            index,
            root: path.to_path_buf(),
        })
    }

    /// The workspace root path (parent of .rlm/).
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Write an object, index it, and return its hash.
    pub fn put<T: Storable>(&self, obj: &T) -> Result<Hash> {
        let hash = self.store.write(obj)?;
        // Best-effort indexing: if it fails, the object is still stored.
        let _ = self.index.index_object(&hash, &self.store);
        Ok(hash)
    }

    /// Read an object by hash.
    pub fn get<T: Storable>(&self, hash: &Hash) -> Result<Option<T>> {
        self.store.read(hash)
    }

    /// Resolve a ref to a hash.
    pub fn get_ref_hash(&self, name: &str) -> Result<Option<Hash>> {
        self.refs.read(name)
    }

    /// Resolve a ref and read the object it points to.
    pub fn get_ref<T: Storable>(&self, name: &str) -> Result<Option<T>> {
        match self.refs.read(name)? {
            Some(hash) => self.store.read(&hash),
            None => Ok(None),
        }
    }

    /// Update a ref to point to a new hash.
    pub fn set_ref(&self, name: &str, hash: &Hash) -> Result<()> {
        self.refs.write(name, hash)
    }

    /// The spec's three-step mutation pattern:
    /// 1. Write immutable objects
    /// 2. Record an Event
    /// 3. Update ref(s) using CAS
    ///
    /// This helper performs steps 2-3 atomically (Event write + ref CAS).
    /// The caller is responsible for writing objects (step 1) beforehand.
    pub fn commit_mutation(
        &self,
        event: &Event,
        ref_updates: &[(&str, Hash, Hash)], // (name, expected, new)
    ) -> Result<Hash> {
        // Write the event (and index it).
        let event_hash = self.put(event)?;

        // CAS all refs. If any fails, the event is still written (harmless,
        // since objects are immutable) but the refs are not updated.
        for (name, expected, new) in ref_updates {
            self.refs.cas(name, expected, new)?;
        }

        Ok(event_hash)
    }

    /// Garbage collection: remove objects not reachable from any ref.
    pub fn gc(&self) -> Result<GcReport> {
        // Collect all ref targets.
        let all_refs = self.refs.list("")?;
        let ref_targets: Vec<Hash> = all_refs.iter().map(|r| r.target).collect();

        // Find all reachable objects.
        let reachable = reachable_from(&self.store, &ref_targets)?;

        // Find all stored objects.
        let all_hashes = self.store.all_hashes()?;
        let total = all_hashes.len();

        // Remove unreachable.
        let mut removed = Vec::new();
        for hash in &all_hashes {
            if !reachable.contains(hash) {
                self.store.remove(hash)?;
                removed.push(*hash);
            }
        }

        Ok(GcReport {
            total_objects: total,
            reachable_objects: reachable.len(),
            removed_objects: removed.len(),
            removed_hashes: removed,
        })
    }

    /// Rebuild the secondary index from scratch.
    /// Use after gc, import, or if the index is suspected corrupt.
    pub fn rebuild_index(&self) -> Result<usize> {
        self.index.rebuild(&self.store)
    }

    /// Export an object and all reachable objects as JSON.
    pub fn export_json(&self, root: &Hash, writer: &mut dyn Write) -> Result<()> {
        let reachable = reachable_from(&self.store, &[*root])?;
        let mut entries = Vec::new();

        for hash in &reachable {
            if let Some(env) = self.store.read_raw(hash)? {
                let json_value: serde_json::Value = match env.object_type {
                    crate::types::ObjectType::Atom => {
                        let obj = Atom::from_hashable_bytes(&env.content)?;
                        serde_json::json!({
                            "type": "Atom",
                            "hash": hash.to_hex(),
                            "data": serde_json::to_value(&obj)
                                .map_err(|e| Error::Serialization(e.to_string()))?
                        })
                    }
                    crate::types::ObjectType::Frame => {
                        let obj = Frame::from_hashable_bytes(&env.content)?;
                        serde_json::json!({
                            "type": "Frame",
                            "hash": hash.to_hex(),
                            "data": serde_json::to_value(&obj)
                                .map_err(|e| Error::Serialization(e.to_string()))?
                        })
                    }
                    crate::types::ObjectType::Event => {
                        let obj = Event::from_hashable_bytes(&env.content)?;
                        serde_json::json!({
                            "type": "Event",
                            "hash": hash.to_hex(),
                            "data": serde_json::to_value(&obj)
                                .map_err(|e| Error::Serialization(e.to_string()))?
                        })
                    }
                };
                entries.push(json_value);
            }
        }

        let output = serde_json::json!({ "objects": entries });
        serde_json::to_writer_pretty(writer, &output)
            .map_err(|e| Error::Serialization(e.to_string()))?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;
    use chrono::{DateTime, Utc};
    use tempfile::TempDir;

    fn fixed_ts() -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc)
    }

    fn make_atom(text: &str) -> Atom {
        Atom {
            kind: AtomKind::ConceptDefinition,
            content: AtomContent::text(text),
            metadata: AtomMetadata {
                created_at: fixed_ts(),
                tags: vec![],
            },
        }
    }

    #[test]
    fn test_init_and_open() {
        let dir = TempDir::new().unwrap();
        let path = dir.path();

        // Init should succeed.
        let ws = Workspace::init(path).unwrap();
        assert!(path.join(".rlm").exists());
        assert!(path.join(".rlm/objects").exists());
        assert!(path.join(".rlm/refs").exists());
        assert!(path.join(".rlm/config").exists());
        drop(ws);

        // Second init should fail.
        assert!(Workspace::init(path).is_err());

        // Open should succeed.
        let _ws = Workspace::open(path).unwrap();
    }

    #[test]
    fn test_open_nonexistent() {
        let dir = TempDir::new().unwrap();
        assert!(Workspace::open(dir.path()).is_err());
    }

    #[test]
    fn test_put_get_roundtrip() {
        let dir = TempDir::new().unwrap();
        let ws = Workspace::init(dir.path()).unwrap();

        let atom = make_atom("test content");
        let hash = ws.put(&atom).unwrap();
        let retrieved: Atom = ws.get(&hash).unwrap().unwrap();
        assert_eq!(atom, retrieved);
    }

    #[test]
    fn test_ref_lifecycle() {
        let dir = TempDir::new().unwrap();
        let ws = Workspace::init(dir.path()).unwrap();

        let atom = make_atom("course root");
        let hash = ws.put(&atom).unwrap();

        ws.set_ref("course/structure", &hash).unwrap();
        let resolved = ws.get_ref_hash("course/structure").unwrap();
        assert_eq!(resolved, Some(hash));

        let obj: Atom = ws.get_ref("course/structure").unwrap().unwrap();
        assert_eq!(obj, atom);
    }

    #[test]
    fn test_gc_removes_orphans() {
        let dir = TempDir::new().unwrap();
        let ws = Workspace::init(dir.path()).unwrap();

        // Write some connected objects.
        let concept = make_atom("binary search");
        let ch = ws.put(&concept).unwrap();

        let lesson = Frame {
            kind: FrameKind::Lesson,
            edges: vec![Edge {
                label: EdgeLabel::CoversConcept,
                target: ch,
                weight: None,
                annotation: None,
            }],
            metadata: FrameMetadata {
                created_at: fixed_ts(),
                tags: vec![],
                label: None,
                label_in_hash: false,
            },
        };
        let lh = ws.put(&lesson).unwrap();
        ws.set_ref("course/structure", &lh).unwrap();

        // Write an orphan.
        let orphan = make_atom("orphan");
        let oh = ws.put(&orphan).unwrap();
        assert!(ws.store.exists(&oh));

        // GC should remove the orphan.
        let report = ws.gc().unwrap();
        assert_eq!(report.removed_objects, 1);
        assert!(report.removed_hashes.contains(&oh));
        assert!(!ws.store.exists(&oh));
        // Connected objects should survive.
        assert!(ws.store.exists(&ch));
        assert!(ws.store.exists(&lh));
    }

    #[test]
    fn test_gc_empty_workspace() {
        let dir = TempDir::new().unwrap();
        let ws = Workspace::init(dir.path()).unwrap();
        let report = ws.gc().unwrap();
        assert_eq!(report.total_objects, 0);
        assert_eq!(report.removed_objects, 0);
    }

    #[test]
    fn test_commit_mutation() {
        let dir = TempDir::new().unwrap();
        let ws = Workspace::init(dir.path()).unwrap();

        // Initial student model.
        let concept = make_atom("recursion");
        let ch = ws.put(&concept).unwrap();

        let model_v1 = Frame {
            kind: FrameKind::StudentModel,
            edges: vec![Edge {
                label: EdgeLabel::MasteryEstimate,
                target: ch,
                weight: Some(0.3),
                annotation: None,
            }],
            metadata: FrameMetadata {
                created_at: fixed_ts(),
                tags: vec![],
                label: None,
                label_in_hash: false,
            },
        };
        let m1h = ws.put(&model_v1).unwrap();
        ws.set_ref("student/alice/mastery", &m1h).unwrap();

        // Step 1: Write new objects.
        let model_v2 = Frame {
            kind: FrameKind::StudentModel,
            edges: vec![Edge {
                label: EdgeLabel::MasteryEstimate,
                target: ch,
                weight: Some(0.7),
                annotation: Some(serde_json::json!({"reason": "quiz passed"})),
            }],
            metadata: FrameMetadata {
                created_at: fixed_ts(),
                tags: vec![],
                label: None,
                label_in_hash: false,
            },
        };
        let m2h = ws.put(&model_v2).unwrap();

        // Step 2+3: Record event and CAS ref.
        let event = Event {
            kind: EventKind::StudentModelUpdate,
            parents: vec![],
            inputs: vec![EventRef {
                hash: m1h,
                role: "prior_model".into(),
            }],
            outputs: vec![EventRef {
                hash: m2h,
                role: "updated_model".into(),
            }],
            trace: CallTrace::empty(),
            metadata: EventMetadata {
                timestamp: fixed_ts(),
                tags: vec![],
            },
        };
        let event_hash = ws
            .commit_mutation(&event, &[("student/alice/mastery", m1h, m2h)])
            .unwrap();

        // Verify.
        assert!(ws.store.exists(&event_hash));
        let current = ws.get_ref_hash("student/alice/mastery").unwrap().unwrap();
        assert_eq!(current, m2h);
    }

    #[test]
    fn test_commit_mutation_cas_failure() {
        let dir = TempDir::new().unwrap();
        let ws = Workspace::init(dir.path()).unwrap();

        let h1 = ws.put(&make_atom("v1")).unwrap();
        let h2 = ws.put(&make_atom("v2")).unwrap();
        let h_wrong = Hash::compute(b"wrong expectation");
        ws.set_ref("HEAD", &h1).unwrap();

        let event = Event {
            kind: EventKind::Admin,
            parents: vec![],
            inputs: vec![],
            outputs: vec![],
            trace: CallTrace::empty(),
            metadata: EventMetadata {
                timestamp: fixed_ts(),
                tags: vec![],
            },
        };

        // CAS should fail because expected doesn't match.
        let result = ws.commit_mutation(&event, &[("HEAD", h_wrong, h2)]);
        assert!(result.is_err());
        // Ref should be unchanged.
        assert_eq!(ws.get_ref_hash("HEAD").unwrap(), Some(h1));
    }

    #[test]
    fn test_export_json() {
        let dir = TempDir::new().unwrap();
        let ws = Workspace::init(dir.path()).unwrap();

        let concept = make_atom("test concept");
        let ch = ws.put(&concept).unwrap();
        let lesson = Frame {
            kind: FrameKind::Lesson,
            edges: vec![Edge {
                label: EdgeLabel::CoversConcept,
                target: ch,
                weight: None,
                annotation: None,
            }],
            metadata: FrameMetadata {
                created_at: fixed_ts(),
                tags: vec![],
                label: None,
                label_in_hash: false,
            },
        };
        let lh = ws.put(&lesson).unwrap();

        let mut buf = Vec::new();
        ws.export_json(&lh, &mut buf).unwrap();
        let json: serde_json::Value = serde_json::from_slice(&buf).unwrap();
        let objects = json["objects"].as_array().unwrap();
        assert_eq!(objects.len(), 2); // lesson frame + concept atom
    }

    #[test]
    fn test_workspace_persists_across_open_close() {
        let dir = TempDir::new().unwrap();

        // Create workspace, write data, drop.
        {
            let ws = Workspace::init(dir.path()).unwrap();
            let atom = make_atom("persistent");
            let hash = ws.put(&atom).unwrap();
            ws.set_ref("HEAD", &hash).unwrap();
        }

        // Reopen and verify.
        {
            let ws = Workspace::open(dir.path()).unwrap();
            let hash = ws.get_ref_hash("HEAD").unwrap().unwrap();
            let atom: Atom = ws.get(&hash).unwrap().unwrap();
            assert_eq!(atom.content.text, "persistent");
        }
    }

    #[test]
    fn test_per_student_ref_namespaces() {
        let dir = TempDir::new().unwrap();
        let ws = Workspace::init(dir.path()).unwrap();

        let alice_model = make_atom("alice model");
        let ah = ws.put(&alice_model).unwrap();
        let bob_model = make_atom("bob model");
        let bh = ws.put(&bob_model).unwrap();

        ws.set_ref("student/alice/mastery", &ah).unwrap();
        ws.set_ref("student/bob/mastery", &bh).unwrap();

        // Each student has independent refs.
        assert_eq!(ws.get_ref_hash("student/alice/mastery").unwrap(), Some(ah));
        assert_eq!(ws.get_ref_hash("student/bob/mastery").unwrap(), Some(bh));
        assert_ne!(ah, bh);

        // Listing student/ should return both.
        let student_refs = ws.refs.list("student").unwrap();
        assert_eq!(student_refs.len(), 2);
    }
}
