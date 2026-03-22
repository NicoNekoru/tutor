use std::path::Path;

use rusqlite::{params, Connection};

use crate::envelope::Storable;
use crate::error::{Error, Result};
use crate::hash::Hash;
use crate::store::ObjectStore;
use crate::types::*;

/// Secondary indexes backed by SQLite.
///
/// All data here is DERIVED and rebuildable from the object store.
/// Missing or corrupt indexes degrade query performance, not correctness.
pub struct Index {
    conn: Connection,
}

impl Index {
    /// Open (or create) the index database.
    pub fn open(rlm_root: &Path) -> Result<Self> {
        let index_dir = rlm_root.join("index");
        std::fs::create_dir_all(&index_dir).map_err(|e| Error::io(e, &index_dir))?;
        let db_path = index_dir.join("index.sqlite3");
        let conn =
            Connection::open(&db_path).map_err(|e| Error::Serialization(e.to_string()))?;
        let idx = Index { conn };
        idx.create_tables()?;
        Ok(idx)
    }

    /// Open an in-memory index (for testing).
    pub fn open_memory() -> Result<Self> {
        let conn = Connection::open_in_memory().map_err(|e| Error::Serialization(e.to_string()))?;
        let idx = Index { conn };
        idx.create_tables()?;
        Ok(idx)
    }

    fn create_tables(&self) -> Result<()> {
        self.conn
            .execute_batch(
                "
            CREATE TABLE IF NOT EXISTS objects (
                hash        BLOB PRIMARY KEY,
                type_code   INTEGER NOT NULL,
                kind        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                label       TEXT
            );

            CREATE TABLE IF NOT EXISTS tags (
                hash    BLOB NOT NULL,
                tag     TEXT NOT NULL,
                PRIMARY KEY (hash, tag)
            );
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

            CREATE TABLE IF NOT EXISTS edges (
                source_hash BLOB NOT NULL,
                target_hash BLOB NOT NULL,
                label       TEXT NOT NULL,
                weight      REAL,
                PRIMARY KEY (source_hash, target_hash, label)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_hash, label);
            CREATE INDEX IF NOT EXISTS idx_edges_label ON edges(label);

            CREATE TABLE IF NOT EXISTS events (
                hash        BLOB PRIMARY KEY,
                kind        TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                call_depth  INTEGER,
                parent_call BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, timestamp);
        ",
            )
            .map_err(|e| Error::Serialization(e.to_string()))?;
        Ok(())
    }

    /// Index a single object (incremental update). Idempotent.
    pub fn index_object(&self, hash: &Hash, store: &ObjectStore) -> Result<()> {
        let env = match store.read_raw(hash)? {
            Some(e) => e,
            None => return Ok(()),
        };

        match env.object_type {
            ObjectType::Atom => {
                let atom = Atom::from_hashable_bytes(&env.content)?;
                self.index_atom(hash, &atom)?;
            }
            ObjectType::Frame => {
                let frame = Frame::from_hashable_bytes(&env.content)?;
                self.index_frame(hash, &frame)?;
            }
            ObjectType::Event => {
                let event = Event::from_hashable_bytes(&env.content)?;
                self.index_event(hash, &event)?;
            }
        }
        Ok(())
    }

    fn index_atom(&self, hash: &Hash, atom: &Atom) -> Result<()> {
        let hash_bytes = hash.as_bytes().as_slice();
        let kind = format!("{:?}", atom.kind);
        let created = atom.metadata.created_at.to_rfc3339();

        self.conn
            .execute(
                "INSERT OR REPLACE INTO objects (hash, type_code, kind, created_at, label) VALUES (?1, ?2, ?3, ?4, NULL)",
                params![hash_bytes, ObjectType::Atom as u8, kind, created],
            )
            .map_err(|e| Error::Serialization(e.to_string()))?;

        // Tags
        for tag in &atom.metadata.tags {
            self.conn
                .execute(
                    "INSERT OR IGNORE INTO tags (hash, tag) VALUES (?1, ?2)",
                    params![hash_bytes, tag],
                )
                .map_err(|e| Error::Serialization(e.to_string()))?;
        }

        Ok(())
    }

    fn index_frame(&self, hash: &Hash, frame: &Frame) -> Result<()> {
        let hash_bytes = hash.as_bytes().as_slice();
        let kind = format!("{:?}", frame.kind);
        let created = frame.metadata.created_at.to_rfc3339();
        let label = frame.metadata.label.as_deref();

        self.conn
            .execute(
                "INSERT OR REPLACE INTO objects (hash, type_code, kind, created_at, label) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![hash_bytes, ObjectType::Frame as u8, kind, created, label],
            )
            .map_err(|e| Error::Serialization(e.to_string()))?;

        // Tags
        for tag in &frame.metadata.tags {
            self.conn
                .execute(
                    "INSERT OR IGNORE INTO tags (hash, tag) VALUES (?1, ?2)",
                    params![hash_bytes, tag],
                )
                .map_err(|e| Error::Serialization(e.to_string()))?;
        }

        // Edges
        for edge in &frame.edges {
            let target_bytes = edge.target.as_bytes().as_slice();
            let label_str = format!("{:?}", edge.label);
            self.conn
                .execute(
                    "INSERT OR REPLACE INTO edges (source_hash, target_hash, label, weight) VALUES (?1, ?2, ?3, ?4)",
                    params![hash_bytes, target_bytes, label_str, edge.weight],
                )
                .map_err(|e| Error::Serialization(e.to_string()))?;
        }

        Ok(())
    }

    fn index_event(&self, hash: &Hash, event: &Event) -> Result<()> {
        let hash_bytes = hash.as_bytes().as_slice();
        let kind = format!("{:?}", event.kind);
        let timestamp = event.metadata.timestamp.to_rfc3339();
        let parent_call = event.trace.parent_call.as_ref().map(|h| h.as_bytes().to_vec());

        self.conn
            .execute(
                "INSERT OR REPLACE INTO objects (hash, type_code, kind, created_at, label) VALUES (?1, ?2, ?3, ?4, NULL)",
                params![hash_bytes, ObjectType::Event as u8, kind, timestamp],
            )
            .map_err(|e| Error::Serialization(e.to_string()))?;

        self.conn
            .execute(
                "INSERT OR REPLACE INTO events (hash, kind, timestamp, call_depth, parent_call) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![hash_bytes, kind, timestamp, event.trace.call_depth, parent_call],
            )
            .map_err(|e| Error::Serialization(e.to_string()))?;

        // Tags
        for tag in &event.metadata.tags {
            self.conn
                .execute(
                    "INSERT OR IGNORE INTO tags (hash, tag) VALUES (?1, ?2)",
                    params![hash_bytes, tag],
                )
                .map_err(|e| Error::Serialization(e.to_string()))?;
        }

        Ok(())
    }

    // ===================================================================
    // Query methods
    // ===================================================================

    /// Find all Atoms of a given kind.
    pub fn atoms_by_kind(&self, kind: AtomKind) -> Result<Vec<Hash>> {
        let kind_str = format!("{:?}", kind);
        self.query_hashes(
            "SELECT hash FROM objects WHERE type_code = ?1 AND kind = ?2",
            params![ObjectType::Atom as u8, kind_str],
        )
    }

    /// Find all Frames of a given kind.
    pub fn frames_by_kind(&self, kind: FrameKind) -> Result<Vec<Hash>> {
        let kind_str = format!("{:?}", kind);
        self.query_hashes(
            "SELECT hash FROM objects WHERE type_code = ?1 AND kind = ?2",
            params![ObjectType::Frame as u8, kind_str],
        )
    }

    /// Find all Events of a given kind.
    pub fn events_by_kind(&self, kind: EventKind) -> Result<Vec<Hash>> {
        let kind_str = format!("{:?}", kind);
        self.query_hashes(
            "SELECT hash FROM events WHERE kind = ?1",
            params![kind_str],
        )
    }

    /// Find all objects with a given tag.
    pub fn by_tag(&self, tag: &str) -> Result<Vec<Hash>> {
        self.query_hashes("SELECT hash FROM tags WHERE tag = ?1", params![tag])
    }

    /// Reverse edge lookup: find all Frames that have an edge pointing to `target`.
    pub fn reverse_edges(&self, target: &Hash) -> Result<Vec<(Hash, String)>> {
        let target_bytes = target.as_bytes().as_slice();
        let mut stmt = self
            .conn
            .prepare("SELECT source_hash, label FROM edges WHERE target_hash = ?1")
            .map_err(|e| Error::Serialization(e.to_string()))?;

        let rows = stmt
            .query_map(params![target_bytes], |row| {
                let hash_bytes: Vec<u8> = row.get(0)?;
                let label: String = row.get(1)?;
                Ok((hash_bytes, label))
            })
            .map_err(|e| Error::Serialization(e.to_string()))?;

        let mut results = Vec::new();
        for row in rows {
            let (bytes, label) = row.map_err(|e| Error::Serialization(e.to_string()))?;
            if bytes.len() == 32 {
                let mut arr = [0u8; 32];
                arr.copy_from_slice(&bytes);
                results.push((Hash::from_bytes(arr), label));
            }
        }
        Ok(results)
    }

    /// Reverse edge lookup filtered by label.
    pub fn reverse_edges_by_label(
        &self,
        target: &Hash,
        label: EdgeLabel,
    ) -> Result<Vec<Hash>> {
        let target_bytes = target.as_bytes().as_slice();
        let label_str = format!("{:?}", label);
        self.query_hashes(
            "SELECT source_hash FROM edges WHERE target_hash = ?1 AND label = ?2",
            params![target_bytes, label_str],
        )
    }

    /// Find the N most recent Events, optionally filtered by kind.
    pub fn recent_events(&self, n: usize, kind: Option<EventKind>) -> Result<Vec<Hash>> {
        match kind {
            Some(k) => {
                let kind_str = format!("{:?}", k);
                self.query_hashes(
                    "SELECT hash FROM events WHERE kind = ?1 ORDER BY timestamp DESC LIMIT ?2",
                    params![kind_str, n],
                )
            }
            None => self.query_hashes(
                "SELECT hash FROM events ORDER BY timestamp DESC LIMIT ?1",
                params![n],
            ),
        }
    }

    /// Find Events in a time range.
    pub fn events_in_range(&self, after: &str, before: &str) -> Result<Vec<Hash>> {
        self.query_hashes(
            "SELECT hash FROM events WHERE timestamp > ?1 AND timestamp < ?2 ORDER BY timestamp",
            params![after, before],
        )
    }

    /// Rebuild the entire index from the object store.
    pub fn rebuild(&self, store: &ObjectStore) -> Result<usize> {
        // Clear all tables.
        self.conn
            .execute_batch(
                "DELETE FROM objects; DELETE FROM tags; DELETE FROM edges; DELETE FROM events;",
            )
            .map_err(|e| Error::Serialization(e.to_string()))?;

        let all_hashes = store.all_hashes()?;
        let count = all_hashes.len();
        for hash in &all_hashes {
            self.index_object(hash, store)?;
        }
        Ok(count)
    }

    /// Count objects by type (for diagnostics).
    pub fn object_counts(&self) -> Result<(usize, usize, usize)> {
        let atoms: i64 = self
            .conn
            .query_row(
                "SELECT COUNT(*) FROM objects WHERE type_code = ?1",
                params![ObjectType::Atom as u8],
                |row| row.get(0),
            )
            .map_err(|e| Error::Serialization(e.to_string()))?;
        let frames: i64 = self
            .conn
            .query_row(
                "SELECT COUNT(*) FROM objects WHERE type_code = ?1",
                params![ObjectType::Frame as u8],
                |row| row.get(0),
            )
            .map_err(|e| Error::Serialization(e.to_string()))?;
        let events: i64 = self
            .conn
            .query_row(
                "SELECT COUNT(*) FROM objects WHERE type_code = ?1",
                params![ObjectType::Event as u8],
                |row| row.get(0),
            )
            .map_err(|e| Error::Serialization(e.to_string()))?;
        Ok((atoms as usize, frames as usize, events as usize))
    }

    // Helper: execute a query that returns a single hash column.
    fn query_hashes(&self, sql: &str, params: impl rusqlite::Params) -> Result<Vec<Hash>> {
        let mut stmt = self
            .conn
            .prepare(sql)
            .map_err(|e| Error::Serialization(e.to_string()))?;
        let rows = stmt
            .query_map(params, |row| {
                let bytes: Vec<u8> = row.get(0)?;
                Ok(bytes)
            })
            .map_err(|e| Error::Serialization(e.to_string()))?;

        let mut results = Vec::new();
        for row in rows {
            let bytes = row.map_err(|e| Error::Serialization(e.to_string()))?;
            if bytes.len() == 32 {
                let mut arr = [0u8; 32];
                arr.copy_from_slice(&bytes);
                results.push(Hash::from_bytes(arr));
            }
        }
        Ok(results)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{DateTime, Utc};
    use tempfile::TempDir;

    fn fixed_ts() -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc)
    }

    fn ts(rfc: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(rfc)
            .unwrap()
            .with_timezone(&Utc)
    }

    fn make_atom(kind: AtomKind, text: &str, tags: Vec<String>) -> Atom {
        Atom {
            kind,
            content: AtomContent::text(text),
            metadata: AtomMetadata { created_at: fixed_ts(), tags },
        }
    }

    fn setup_store() -> (TempDir, ObjectStore) {
        let dir = TempDir::new().unwrap();
        let rlm_root = dir.path().join(".rlm");
        std::fs::create_dir_all(&rlm_root).unwrap();
        let store = ObjectStore::open(&rlm_root).unwrap();
        store.init_dirs().unwrap();
        (dir, store)
    }

    #[test]
    fn test_index_and_query_atoms() {
        let (_dir, store) = setup_store();
        let idx = Index::open_memory().unwrap();

        let a1 = make_atom(AtomKind::ConceptDefinition, "binary search", vec!["algo".into()]);
        let a2 = make_atom(AtomKind::ConceptDefinition, "linear search", vec!["algo".into()]);
        let a3 = make_atom(AtomKind::ProblemStatement, "find element", vec!["practice".into()]);
        let h1 = store.write(&a1).unwrap();
        let h2 = store.write(&a2).unwrap();
        let h3 = store.write(&a3).unwrap();

        idx.index_object(&h1, &store).unwrap();
        idx.index_object(&h2, &store).unwrap();
        idx.index_object(&h3, &store).unwrap();

        let concepts = idx.atoms_by_kind(AtomKind::ConceptDefinition).unwrap();
        assert_eq!(concepts.len(), 2);
        assert!(concepts.contains(&h1));
        assert!(concepts.contains(&h2));

        let problems = idx.atoms_by_kind(AtomKind::ProblemStatement).unwrap();
        assert_eq!(problems.len(), 1);
        assert!(problems.contains(&h3));

        let algo_tagged = idx.by_tag("algo").unwrap();
        assert_eq!(algo_tagged.len(), 2);

        let practice_tagged = idx.by_tag("practice").unwrap();
        assert_eq!(practice_tagged.len(), 1);
    }

    #[test]
    fn test_index_frame_and_reverse_edges() {
        let (_dir, store) = setup_store();
        let idx = Index::open_memory().unwrap();

        let c1 = store.write(&make_atom(AtomKind::ConceptDefinition, "concept A", vec![])).unwrap();
        let c2 = store.write(&make_atom(AtomKind::ConceptDefinition, "concept B", vec![])).unwrap();
        idx.index_object(&c1, &store).unwrap();
        idx.index_object(&c2, &store).unwrap();

        let frame = Frame {
            kind: FrameKind::Lesson,
            edges: vec![
                Edge { label: EdgeLabel::CoversConcept, target: c1, weight: None, annotation: None },
                Edge { label: EdgeLabel::CoversConcept, target: c2, weight: None, annotation: None },
                Edge { label: EdgeLabel::Prerequisite, target: Hash::compute(b"other lesson"), weight: None, annotation: None },
            ],
            metadata: FrameMetadata { created_at: fixed_ts(), tags: vec![], label: Some("test-lesson".into()), label_in_hash: true },
        };
        let fh = store.write(&frame).unwrap();
        idx.index_object(&fh, &store).unwrap();

        // Reverse edges: who points to c1?
        let rev = idx.reverse_edges(&c1).unwrap();
        assert_eq!(rev.len(), 1);
        assert_eq!(rev[0].0, fh);
        assert_eq!(rev[0].1, "CoversConcept");

        // Reverse edges by label
        let rev_concept = idx.reverse_edges_by_label(&c1, EdgeLabel::CoversConcept).unwrap();
        assert_eq!(rev_concept.len(), 1);
        let rev_prereq = idx.reverse_edges_by_label(&c1, EdgeLabel::Prerequisite).unwrap();
        assert_eq!(rev_prereq.len(), 0);

        // Frame kind query
        let lessons = idx.frames_by_kind(FrameKind::Lesson).unwrap();
        assert_eq!(lessons.len(), 1);
    }

    #[test]
    fn test_index_events_and_temporal_queries() {
        let (_dir, store) = setup_store();
        let idx = Index::open_memory().unwrap();

        let e1 = Event {
            kind: EventKind::SessionStart,
            parents: vec![], inputs: vec![], outputs: vec![],
            trace: CallTrace::empty(),
            metadata: EventMetadata { timestamp: ts("2026-03-20T10:00:00Z"), tags: vec![] },
        };
        let e2 = Event {
            kind: EventKind::ModelCall,
            parents: vec![], inputs: vec![], outputs: vec![],
            trace: CallTrace { call_depth: 0, ..CallTrace::empty() },
            metadata: EventMetadata { timestamp: ts("2026-03-20T10:05:00Z"), tags: vec![] },
        };
        let e3 = Event {
            kind: EventKind::ModelCall,
            parents: vec![], inputs: vec![], outputs: vec![],
            trace: CallTrace { call_depth: 1, ..CallTrace::empty() },
            metadata: EventMetadata { timestamp: ts("2026-03-20T10:10:00Z"), tags: vec![] },
        };
        let e4 = Event {
            kind: EventKind::SessionEnd,
            parents: vec![], inputs: vec![], outputs: vec![],
            trace: CallTrace::empty(),
            metadata: EventMetadata { timestamp: ts("2026-03-20T10:15:00Z"), tags: vec![] },
        };

        let h1 = store.write(&e1).unwrap();
        let h2 = store.write(&e2).unwrap();
        let h3 = store.write(&e3).unwrap();
        let h4 = store.write(&e4).unwrap();
        for h in &[h1, h2, h3, h4] {
            idx.index_object(h, &store).unwrap();
        }

        // Kind queries
        let model_calls = idx.events_by_kind(EventKind::ModelCall).unwrap();
        assert_eq!(model_calls.len(), 2);

        let sessions = idx.events_by_kind(EventKind::SessionStart).unwrap();
        assert_eq!(sessions.len(), 1);

        // Recent events
        let recent = idx.recent_events(2, None).unwrap();
        assert_eq!(recent.len(), 2);
        assert_eq!(recent[0], h4, "Most recent should be SessionEnd");

        let recent_calls = idx.recent_events(1, Some(EventKind::ModelCall)).unwrap();
        assert_eq!(recent_calls.len(), 1);
        assert_eq!(recent_calls[0], h3);

        // Time range
        let range = idx.events_in_range("2026-03-20T10:03:00Z", "2026-03-20T10:12:00Z").unwrap();
        assert_eq!(range.len(), 2); // e2 and e3
    }

    #[test]
    fn test_rebuild_index() {
        let (_dir, store) = setup_store();
        let idx = Index::open_memory().unwrap();

        let a1 = store.write(&make_atom(AtomKind::ConceptDefinition, "one", vec![])).unwrap();
        let a2 = store.write(&make_atom(AtomKind::LessonBody, "two", vec![])).unwrap();
        let f1 = store.write(&Frame {
            kind: FrameKind::Lesson,
            edges: vec![Edge { label: EdgeLabel::CoversConcept, target: a1, weight: None, annotation: None }],
            metadata: FrameMetadata { created_at: fixed_ts(), tags: vec![], label: None, label_in_hash: false },
        }).unwrap();

        let count = idx.rebuild(&store).unwrap();
        assert_eq!(count, 3);

        let (atoms, frames, events) = idx.object_counts().unwrap();
        assert_eq!(atoms, 2);
        assert_eq!(frames, 1);
        assert_eq!(events, 0);

        // Verify queries work after rebuild
        let concepts = idx.atoms_by_kind(AtomKind::ConceptDefinition).unwrap();
        assert_eq!(concepts.len(), 1);
        assert!(concepts.contains(&a1));

        let rev = idx.reverse_edges(&a1).unwrap();
        assert_eq!(rev.len(), 1);
        assert_eq!(rev[0].0, f1);
    }

    #[test]
    fn test_index_idempotent() {
        let (_dir, store) = setup_store();
        let idx = Index::open_memory().unwrap();

        let a = make_atom(AtomKind::ConceptDefinition, "idempotent", vec!["test".into()]);
        let h = store.write(&a).unwrap();

        // Index twice — should not duplicate.
        idx.index_object(&h, &store).unwrap();
        idx.index_object(&h, &store).unwrap();

        let concepts = idx.atoms_by_kind(AtomKind::ConceptDefinition).unwrap();
        assert_eq!(concepts.len(), 1);

        let tagged = idx.by_tag("test").unwrap();
        assert_eq!(tagged.len(), 1);
    }

    #[test]
    fn test_on_disk_index() {
        let dir = TempDir::new().unwrap();
        let rlm_root = dir.path().join(".rlm");
        std::fs::create_dir_all(&rlm_root).unwrap();
        let store = ObjectStore::open(&rlm_root).unwrap();
        store.init_dirs().unwrap();

        // Write and index
        {
            let idx = Index::open(&rlm_root).unwrap();
            let a = make_atom(AtomKind::ConceptDefinition, "persistent", vec![]);
            let h = store.write(&a).unwrap();
            idx.index_object(&h, &store).unwrap();

            let concepts = idx.atoms_by_kind(AtomKind::ConceptDefinition).unwrap();
            assert_eq!(concepts.len(), 1);
        }

        // Reopen and verify persistence
        {
            let idx = Index::open(&rlm_root).unwrap();
            let concepts = idx.atoms_by_kind(AtomKind::ConceptDefinition).unwrap();
            assert_eq!(concepts.len(), 1);
        }
    }
}
